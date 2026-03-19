import os

import sys
import time
import traceback
import queue
import csv
import numpy as np
from PIL import Image


 #Load ONNX
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from PyQt6.QtCore import QThread, pyqtSignal


class AITaggerWorker(QThread):
     #emit the image path and list of generated tags
    tags_generated = pyqtSignal(str,list)
    engine_ready = pyqtSignal()
    error_signal = pyqtSignal(str)
    queue_updated = pyqtSignal(int)
    def __init__(self):
        super().__init__()
        self.inbox = queue.Queue()
        self.is_running = True
    
    def run(self):
    #OUTER TRY: Catches fatal download or boot errors
        try:  
            print("Ai Engine loading... loading ONNX Runtime") 
            print("Downloading WD14 Auto-Tagger model (only happens once, ~300MB)...")
            
            #Use SmilingWolf's MOAT Architecture
            repo_id = "SmilingWolf/wd-v1-4-moat-tagger-v2"
            
            #Download tagger and the tag dictionary
            model_path = hf_hub_download(repo_id, "model.onnx")
            tags_path = hf_hub_download(repo_id, "selected_tags.csv")
            
            print("Loading art tags into memory")
            self.tags_vocab = []
            with open(tags_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader) # Skip header row
                for row in reader:
                    self.tags_vocab.append(row[1]) # Tag name in second column
            
            print("Warming up ONNX inference engine")
            sess_options = ort.SessionOptions()
            
            #INNER TRY: Hardware Detection
            try:
                # Attempt to use GPU
                print("Attempting to connect to GPU via DirectX...")
                self.session = ort.InferenceSession(
                    model_path, 
                    sess_options=sess_options, 
                    providers=['DmlExecutionProvider'] # Try GPU exclusively first
                )
                
                active_providers = self.session.get_providers()
                if 'DmlExecutionProvider' not in active_providers:
                    raise RuntimeError("DirectML rejected. No compatible DirectX 12 GPU found")
                
                print("SUCCESS: WD14 Art Tagger running on GPU (CUDA)")
                
            except Exception as e:
                #FALLBACK TO CPU
                print(f"GPU missing or unavailable. Falling back to CPU. Reason: {e}")
                
                #Apply the strict OS thread limits so the CPU doesn't freeze the app
                os.environ["OMP_NUM_THREADS"] = "3"
                sess_options.intra_op_num_threads = 3
                sess_options.inter_op_num_threads = 3
                sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                
                print("Booting standard CPU engine...")
                self.session = ort.InferenceSession(
                    model_path, 
                    sess_options=sess_options, 
                    providers=['CPUExecutionProvider'] #Force CPU
                )
                print("SUCCESS: WD14 Art Tagger running on CPU.")

            #tell UI engine is ready
            self.engine_ready.emit()
            
        except Exception as e:
            #crash dump for fatal outer errors
            error_msg = traceback.format_exc()
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
                
            log_path = os.path.join(app_dir, "Vault_Crash_Log.txt")
            
            with open(log_path, "a") as f:
                f.write(f"ENGINE FAILED TO START:\n{error_msg}\n\n")
            return #kill the thread
        
        #Consumer Loop
        while self.is_running:
            image_path = self.inbox.get()
            
            if image_path == "STOP_ENGINE":
                break
            
            try:
                
                
                #open image and convert to rgb
                image= Image.open(image_path).convert("RGB")
                
                #Smart pad image since wd14 expects a perfect 448x448 square
                #pad background so that the ai is not confused and preserve the aspect ratio
                max_dim= max(image.size)
                padded_image = Image.new("RGB",(max_dim,max_dim),(255,255,255))
                padded_image.paste(image,((max_dim - image.size[0])//2,(max_dim-image.size[1])//2))
                
                image_resized = padded_image.resize((448,448),Image.Resampling.LANCZOS)
                
                #Convert to Numpy Array
                image_array = np.array(image_resized,dtype=np.float32)
                image_array = np.expand_dims(image_array,axis=0)#Shape becomes (1, 448, 448, 3)
                
                #Run Inference on the CPU
                input_name = self.session.get_inputs()[0].name
                raw_outputs = self.session.run(None,{input_name: image_array})[0]
                
                
                #Extract Tags
                probs = np.array(raw_outputs[0]) #type:ignore
                THRESHOLD = 0.35 #confidence threshold
                
                generated_tags = []
                
                #0-3 in CSV are ratings, skip them to grab the art description
                for i in range(4,len(probs)):
                    if probs[i]> THRESHOLD:
                        tag_name = self.tags_vocab[i]
                        #clean up danbooru tag formatting
                        clean_tag= tag_name.replace('_',' ')
                        generated_tags.append(clean_tag)
                
                if generated_tags:
                    self.tags_generated.emit(image_path,generated_tags)
                    print(f"AI Tagged {os.path.basename(image_path)}: {generated_tags}")
                
            except Exception as e:
                #---crash log
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
                #Finished the job
                self.inbox.task_done()    
                self.queue_updated.emit(self.inbox.qsize())
                #force the AI to pause for exactly 10 milliseconds. 
                #so that windows has enough free CPU cycles to keep the UI pipsmooth.
                time.sleep(0.01)
    
    #send image paths from Producer(UI) to inbox of Consumer(AI)
    def queue_image(self,image_path):            
        self.inbox.put(image_path)
        self.queue_updated.emit(self.inbox.qsize())
        
    def stop_engine(self):
        self.is_running= False
        self.inbox.put("STOP_ENGINE")
        self.wait()    