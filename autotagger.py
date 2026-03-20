import os

# Disable console loading bars because we have no console
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

import sys
import time
import traceback
import queue
import csv
import gc
import numpy as np
from PIL import Image

# Load ONNX
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from PyQt6.QtCore import QThread, pyqtSignal

class AITaggerWorker(QThread):
    # emit the image path and list of generated tags
    tags_generated = pyqtSignal(str, list)
    engine_ready = pyqtSignal()
    error_signal = pyqtSignal(str)
    queue_updated = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self.inbox = queue.Queue()
        self.is_running = True
        self.session = None # Track if the model is currently in VRAM
        self.model_path = ""
        self.sess_options = ort.SessionOptions()
    
    def load_engine(self):
        print("Warming up ONNX inference engine")
        try:
            # Attempt to use GPU
            print("Attempting to connect to GPU via DirectX...")
            self.session = ort.InferenceSession(
                self.model_path, 
                sess_options=self.sess_options, 
                providers=['DmlExecutionProvider'] # Try GPU exclusively first
            )
            
            active_providers = self.session.get_providers()
            if 'DmlExecutionProvider' not in active_providers:
                raise RuntimeError("DirectML rejected. No compatible DirectX 12 GPU found")
            
            print("SUCCESS: WD14 Art Tagger running on GPU (CUDA/DirectML)")
            
        except Exception as e:
            # FALLBACK TO CPU
            print(f"GPU missing or unavailable. Falling back to CPU. Reason: {e}")
            
            # Apply the strict OS thread limits so the CPU doesn't freeze the app
            os.environ["OMP_NUM_THREADS"] = "3"
            self.sess_options.intra_op_num_threads = 3
            self.sess_options.inter_op_num_threads = 3
            self.sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            
            print("Booting standard CPU engine...")
            self.session = ort.InferenceSession(
                self.model_path, 
                sess_options=self.sess_options, 
                providers=['CPUExecutionProvider'] # Force CPU
            )
            print("SUCCESS: WD14 Art Tagger running on CPU.")

    def run(self):
        # OUTER TRY: Catches fatal download or boot errors
        try:  
            print("Ai Engine loading... loading ONNX Runtime") 
            
            # Figure out where the .exe is currently running from
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Define exactly where the bundled offline files should be
            local_model_path = os.path.join(app_dir, "ai_model", "model.onnx")
            local_tags_path = os.path.join(app_dir, "ai_model", "selected_tags.csv")
            
            # HYBRID CHECK: Do we already have the files bundled locally?
            if os.path.exists(local_model_path) and os.path.exists(local_tags_path):
                print("SUCCESS: Found bundled offline AI model. Skipping download.")
                self.model_path = local_model_path
                tags_path = local_tags_path
            else:
                print("Downloading WD14 Auto-Tagger model (only happens once, ~300MB)...")
                repo_id = "SmilingWolf/wd-v1-4-moat-tagger-v2"
                self.model_path = hf_hub_download(repo_id, "model.onnx")
                tags_path = hf_hub_download(repo_id, "selected_tags.csv")
            
            print("Loading art tags into memory")
            self.tags_vocab = []
            with open(tags_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader) # Skip header row
                for row in reader:
                    self.tags_vocab.append(row[1]) # Tag name in second column
            
            # Load the engine into VRAM for the first time
            self.load_engine()
            
            # tell UI engine is ready
            self.engine_ready.emit()
            
        except Exception as e:
            # crash dump for fatal outer errors
            error_msg = traceback.format_exc()
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
                
            log_path = os.path.join(app_dir, "Vault_Crash_Log.txt")
            
            with open(log_path, "a") as f:
                f.write(f"ENGINE FAILED TO START:\n{error_msg}\n\n")
            return # kill the thread
        
        # Consumer Loop
        while self.is_running:
            image_path = None
            try:
                # 60-second timeout. If no images arrive, it throws queue.Empty
                image_path = self.inbox.get(timeout=60.0)
                
                if image_path == "STOP_ENGINE":
                    break
                
                # If engine is sleeping, wake it up
                if self.session is None:
                    print("Waking AI Engine from sleep...")
                    self.load_engine()
                if self.session is None:
                    continue
                # open image and convert to rgb
                image = Image.open(image_path).convert("RGB")
                
                # Smart pad image since wd14 expects a perfect 448x448 square
                max_dim = max(image.size)
                padded_image = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
                padded_image.paste(image, ((max_dim - image.size[0]) // 2, (max_dim - image.size[1]) // 2))
                image_resized = padded_image.resize((448, 448), Image.Resampling.LANCZOS)
                
                # Convert to Numpy Array & Swap rgb to bgr so human skin is not blue
                image_array = np.array(image_resized, dtype=np.float32)
                image_array = image_array[:, :, ::-1]
                image_array = np.expand_dims(image_array, axis=0) # Shape becomes (1, 448, 448, 3)
                
                # Run Inference
                input_name = self.session.get_inputs()[0].name
                raw_outputs = self.session.run(None, {input_name: image_array})[0]
                
                # Extract Tags
                probs = np.array(raw_outputs[0]) 
                THRESHOLD = 0.35 # confidence threshold
                
                valid_tags = []
                # 0-3 in CSV are ratings, skip them to grab the art description
                for i in range(4, len(probs)):
                    if probs[i] > THRESHOLD:
                        valid_tags.append((probs[i], self.tags_vocab[i]))
                        
                # Sort tags by probability (highest first)
                valid_tags.sort(key=lambda x: x[0], reverse=True)
                
                generated_tags = []
                # Take only the top 4
                for prob, tag_name in valid_tags[:4]:
                    clean_tag = tag_name.replace('_', ' ')
                    generated_tags.append(clean_tag)
                
                if generated_tags:
                    self.tags_generated.emit(image_path, generated_tags)
                    print(f"AI Tagged {os.path.basename(image_path)}: {generated_tags}")
                    
            except queue.Empty:
                # The Garbage Collector: Triggered if idle for 60 seconds
                if self.session is not None:
                    print("AI Engine idle for 60 seconds. Flushing VRAM...")
                    del self.session
                    self.session = None
                    gc.collect() # Force dump
                continue # Keep looping, just stay asleep
                
            except Exception as e:
                # --- crash log
                error_msg = traceback.format_exc()
                if getattr(sys, 'frozen', False):
                    app_dir = os.path.dirname(sys.executable)
                else:
                    app_dir = os.path.dirname(os.path.abspath(__file__))
                    
                log_path = os.path.join(app_dir, "Vault_Crash_Log.txt")
                
                with open(log_path, "a") as f:
                    f.write(f"Crash on {image_path}:\n{error_msg}\n\n")
                
                print(f"AI failed to process {image_path}: {e}")        
                
            finally:
                if 'image_path' in locals() and image_path != "STOP_ENGINE":
                    # Finished the job
                    self.inbox.task_done()    
                    self.queue_updated.emit(self.inbox.qsize())
                    # force the AI to pause for exactly 10 milliseconds. 
                    # so that windows has enough free CPU cycles to keep the UI pipsmooth.
                    time.sleep(0.01)
    
    # send image paths from Producer(UI) to inbox of Consumer(AI)
    def queue_image(self, image_path):            
        self.inbox.put(image_path)
        self.queue_updated.emit(self.inbox.qsize())
        
    def stop_engine(self):
        self.is_running = False
        self.inbox.put("STOP_ENGINE")
        self.wait()