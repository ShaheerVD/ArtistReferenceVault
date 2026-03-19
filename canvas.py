import os
import shutil #copy local files
import urllib.request #download web files
import uuid #generate unique filename for web images
import hashlib
from PyQt6 import QtCore
from PyQt6.QtWidgets import QFrame, QMenu,QListWidgetItem,QVBoxLayout,QStackedWidget,QMessageBox,QLabel,QListWidget,QProgressBar
from PyQt6.QtCore import QSize, QThread, Qt, pyqtSignal,QUrl,QMimeData
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap,QDrag,QIcon,QContextMenuEvent

#multi threading to stop UI freezing when loading large folders

class ImageLoaderThread(QThread):
    image_loaded=pyqtSignal(str, QImage)
    
    def __init__(self,target,valid_extensions):
        super().__init__()
        self.target = target #folder path(str) or list of paths (list)
        self.valid_extensions=valid_extensions
        #setup cache directory
        self.cache_dir = os.path.join(os.getcwd(),'.thumb_cache')
        os.makedirs(self.cache_dir,exist_ok=True)
        
        
    def run(self):
        #get files based on what type of target is received
        files_to_process = []
        
        if isinstance(self.target, str): 
            #if folder then only scan the top level, ignore subfolders
            try:
                for item_name in os.listdir(self.target):
                    full_path = os.path.join(self.target, item_name)
                    #check if it is a file (not a folder) before adding it to the grid
                    if os.path.isfile(full_path):
                        files_to_process.append(full_path)
            except Exception as e:
                print(f"Error reading folder contents: {e}")
                    
        elif isinstance(self.target, list):
           
            #global search list.
            files_to_process = self.target

        #Process all gathered files (with cache)
        for full_path in files_to_process:
            if self.isInterruptionRequested():
                return
                
            ext = os.path.splitext(full_path)[1].lower()
            if ext in self.valid_extensions and os.path.exists(full_path):
                
                #Cache: turn file path into a unique hash
                path_bytes = full_path.encode('utf-8')
                path_hash = hashlib.md5(path_bytes).hexdigest()
                cache_path = os.path.join(self.cache_dir, f"{path_hash}.jpg")
                
                #Check if a thumbnail already exists
                if os.path.exists(cache_path):
                    img = QImage(cache_path)
                    if not img.isNull():
                        self.image_loaded.emit(full_path, img)
                else:
                    #Not in cache: load original image, scale it, and SAVE it to cache
                    img = QImage(full_path)
                    if not img.isNull():
                        scaled_img = img.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        scaled_img.save(cache_path, "JPG", 85) #save it
                        self.image_loaded.emit(full_path, scaled_img)
       
           

#thread to handle image downloads from web(Pinterest,etc)
class WebImageDownloader(QThread):
    download_complete = pyqtSignal(str) #emit saved file path
    
    def __init__(self,url,dest_folder):
        super().__init__()
        self.url=url
        self.dest_folder = dest_folder
        
    def run(self):
        try:
            #disguise as a web browser
            req=urllib.request.Request(self.url,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                #generate random filename unique
                filename=f"web_import_{uuid.uuid4().hex[:8]}.jpg"
                full_path=os.path.join(self.dest_folder,filename)
                
                #write to hdd
                with open(full_path,'wb') as f:
                    f.write(response.read())    
            
            #tell main thread finsihed
            self.download_complete.emit(full_path)
        
        except Exception as e:
            print(f"Failed to download web image: {e}")    
        

#custom QListWidget to display image thumbnails in a grid and allow dragging them onto other applications
class ReferenceGrid(QListWidget):
        def __init__(self):
            super().__init__()
            
            self.setViewMode(QListWidget.ViewMode.IconMode)
            self.setIconSize(QtCore.QSize(150, 150))
            self.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.setSpacing(10)
            self.setMovement(QListWidget.Movement.Static)
            self.setStyleSheet("QListWidget { border: none; background-color: transparent; }")
            self.setDragEnabled(True)
            self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
            self.setSelectionRectVisible(True) #display selection drag box
        
        def mouseMoveEvent(self, event): # type: ignore
            if event.buttons()&Qt.MouseButton.LeftButton:
                super().mouseMoveEvent(event)
            
        def startDrag(self, supportedActions):
            items=self.selectedItems()
            if not items:
                return
            
            drag=QDrag(self)
            mime_data=QMimeData()
            urls=[]
            
            for item in items:
                full_path=item.data(Qt.ItemDataRole.UserRole)
                if full_path:
                    #clean up the path for Windows by replacing backslashes with forward slashes and removing the drive letter if present, to ensure compatibility with other applications that may not handle Windows paths correctly
                    clean_path = os.path.normpath(os.path.abspath(full_path))
                    urls.append(QUrl.fromLocalFile(clean_path))    
                    
            #set the urls in the mime data so that when dragging to other applications, they receive the file paths in a standard format they can understand and handle as file drops. This allows dragging to apps like Photoshop, image viewers, or file explorers that support file drops.
            mime_data.setUrls(urls)
            #also set the text representation of the paths in the mime data for applications that may use it instead of urls. Join multiple paths with newlines to allow dragging multiple files as text.
            paths = "\n".join(url.toLocalFile() for url in urls)
            mime_data.setText(paths)
            
            drag.setMimeData(mime_data)
            
            #if the item has an icon, use it as the drag pixmap for better visual feedback when dragging, otherwise it will use a default blank pixmap which is less intuitive
            if items[0].icon() and not items[0].icon().isNull():
                drag.setPixmap(items[0].icon().pixmap(QSize(100,100)))
            
            #tell os copy move and link are supported but copy is preferred.This allows dragging to applications that only support copy, while still allowing move/link in apps that support it if the user holds modifier keys (like Ctrl for copy or Shift for move) during the drag.
            allowed_actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction
                
            drag.exec(allowed_actions,Qt.DropAction.CopyAction)
        
        def contextMenuEvent(self,event:QContextMenuEvent): #type:ignore
            pos=self.viewport().mapFromGlobal(event.globalPos())#type:ignore
            item = self.itemAt(pos)
            
            #if user right click empty space do nothing
            if item is None:
                return
            #if item isnt part of a multi selection then select the one item only
            if not item.isSelected():
                self.clearSelection()
                item.setSelected(True)
            
            menu = QMenu(self) #type:ignore
            menu.setStyleSheet("background-color: #34495e;color:white;padding:5px;")
            
            #change text based on how many items are selected            
            selected_count= len(self.selectedItems())
            
            #create two distinct delete options
            
            remove_ref_action = menu.addAction(f"Remove {selected_count} Reference(s) from Vault")
            menu.addSeparator()
            delete_perm_action = menu.addAction(f"Delete {selected_count} File(s) Permanently from PC")
            
            action = menu.exec(event.globalPos())
            
            if action==remove_ref_action:
                self.remove_selected_images(permanent=False) 
            elif action ==delete_perm_action:
                self.remove_selected_images(permanent=True)     
        
        def remove_selected_images(self,permanent=False):
            items_to_delete = self.selectedItems()
            
            #show if permanent delete
            if permanent:
                reply = QMessageBox.question(
                    self,
                    "Delete Images",
                    f"Are you sure you want to PERMANENTLY delete {len(items_to_delete)} file(s) from your hard drive?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            #iterate backwards
            for item in reversed(items_to_delete):
                path = item.data(Qt.ItemDataRole.UserRole)
                row = self.row(item)
                self.takeItem(row) #hide from ui
                
                #only touch the OS file system if permanent is True
                if permanent:
                    try:
                        os.remove(path)
                    except Exception as e:
                        print(f"Error deleting file {path}: {e}")
                
                
#this class handles the drag and drop of folders onto the canvas and displays the image grid. It emits a signal when a folder is dropped so the main window can add it to the sidebar. It also has a method to load images from a given folder path and display them as thumbnails in the grid.

class DropCanvas(QFrame):
    #announce a folder dropped, new image path
    folder_dropped=pyqtSignal(str,str)
    image_added = pyqtSignal(str)
    needs_new_folder = pyqtSignal()
    #canvas for image grid
    def __init__(self,db_manager):
        super().__init__()
        self.db=db_manager
        self.setStyleSheet("background-color: #1e1e1e;color: gray;")
        
        self.setAcceptDrops(True)
        
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        #stack to flip between welcome screen and image grid
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        
        #progress bar
        self.progress_bar=QProgressBar()
        self.progress_bar.setRange(0,0) #loop animation
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setStyleSheet("""
            QProgressBar{
                border:none;
                background-color:#1e1e1e;
            }
            QProgressBar::chunk{
                background-color:#3498db;
            }
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        #welcome screen with instructions
        self.welcome_screen = QLabel(
            "Welcome to your Reference Vault!\n\n"
            "📁 Drag & Drop folders or web images here.\n"
            "🔍 Search for images using tags globally at the top.\n"
            "🖱️ Double-click any image to view it full size.\n"
            "🖱️ Right-click images or folders for more options."
        )
        self.welcome_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_screen.setStyleSheet("color: #888888; font-size: 18px;")
        
        #Empty search screen
        self.no_results_screen = QLabel(
            "No images match this search.\n\n"
            "Try a different tag or check your spelling!"
        )
        self.no_results_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_results_screen.setStyleSheet("color: #666666; font-size: 18px;")
        
        #Empty folder
        self.empty_folder_screen = QLabel(
            "This folder has no images inside it.\n\n"
            "If it has subfolders, click them in the sidebar"
        )
        self.empty_folder_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_folder_screen.setStyleSheet("color: #666666; font-size: 18px;")
        
        #thumbnail grid
        self.grid = ReferenceGrid()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QtCore.QSize(150, 150))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setSpacing(10)
        self.grid.setStyleSheet("QListWidget { border: none; background-color: transparent; }")
        self.stack.addWidget(self.welcome_screen)
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.no_results_screen)
        self.stack.addWidget(self.empty_folder_screen)
        
        #allowed image formats
        self.valid_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.webp']
        self.loader_thread=None #to keep reference to the loader thread and prevent garbage collection while running

        #Track currently open folder and background downloads
        self.active_folder=None
        self.active_downloaders =[]
        #Hold dying threads
        self.dying_threads = []
    
    #handle drag enter event
    def dragEnterEvent(self, event): # type: ignore
        #accept the event if it contains urls (files)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("background-color: #2a2a2a;color: white;")
        else:
            event.ignore()
    
    #If the user drags the item out of the canvas, reset the style
    def dragLeaveEvent(self, event): # type: ignore
        self.setStyleSheet("background-color: #1e1e1e;color: gray;")    
                
    #Switches to the empty message if the thread found 0 images
    def check_if_folder_is_empty(self):
        
        if self.grid.count() == 0:
            self.stack.setCurrentWidget(self.empty_folder_screen)
        else:
            self.stack.setCurrentWidget(self.grid)
        
    #triggered when the user drops files onto the canvas determines if web based or local
    def dropEvent(self, event): # type: ignore
        self.setStyleSheet("background-color: #1e1e1e;color: gray;")
        mime = event.mimeData() #detect if the dropped item is a file/folder from the OS or a web link by checking the mime data. If it has urls, it's likely from the OS, if it has text that looks like a URL, it's likely from the web.
        
        if not mime.hasUrls():
            return
        
        for url in mime.urls():
            #image is from the web, Pinterest,google images
            if url.scheme() in ['http', 'https']:
                web_link = url.toString()
                
                if not self.active_folder:
                    self.needs_new_folder.emit()
                
                print("Web link dropped:", {web_link})     
                #check if looking at a folder
                if self.active_folder:
                    print(f"Downloading web image:{web_link}")
                    self.download_web_image(web_link)
                else:
                    print("Error: No folder selected to save web image into!")    
            
            #image is from the local file system    
            elif url.isLocalFile():
                path = url.toLocalFile()
                
                if os.path.isdir(path):
                    #Recursive folder search
                    #find all subfolders
                    for root_dir,sub_dirs,files in os.walk(path):
                    
                        #prevent the app from adding hidden system folders (like .git or .thumb_cache)
                        sub_dirs[:] = [d for d in sub_dirs if not d.startswith('.')]
                        
                        #get the name of the current folder in the tree
                        folder_name = os.path.basename(root_dir)
                        self.folder_dropped.emit(folder_name, root_dir) #emit signal to add folder to sidebar
                
                elif os.path.isfile(path):
                    print(f"file dropped: {path}")
                    if not self.active_folder:
                        self.needs_new_folder.emit()
                    
                    if self.active_folder:
                        self.copy_local_image(path)
                    else:
                        print("Error: No folder selected to copy the image into")        
    
    
    #helper function for copying and thumbnailing
    def copy_local_image(self,source_path):
        #Type guard
        if not self.active_folder or not isinstance(self.active_folder,str):
            print("Safety trigger: no active folder to copy into")
            return
        
        ext= os.path.splitext(source_path)[1].lower()
        if ext in self.valid_extensions:
            filename=os.path.basename(source_path)
            dest_path = os.path.join(self.active_folder, filename)
            #dont crash if a file with same name already exists
            if not os.path.exists(dest_path):
                shutil.copy2(source_path,dest_path)
                print(f"Copied image to: {dest_path}")
                #emit that a new image arrived
                self.image_added.emit(dest_path)
                self.add_single_thumbnail(dest_path)    
    
    #download web image using thread                
    def download_web_image(self,url):
        downloader = WebImageDownloader(url,self.active_folder)
        downloader.download_complete.connect(self.add_single_thumbnail)
        
        #hook into downloader
        self.progress_bar.show()
        downloader.finished.connect(self.progress_bar.hide)
        #emit
        downloader.download_complete.connect(self.image_added.emit)
        
        #image loading progress bar
        self.progress_bar.show()
        downloader.finished.connect(self.progress_bar.hide)
        
        downloader.start()       
        
        #keep reference
        self.active_downloaders.append(downloader)
        #clean old threads 
        self.active_downloaders = [d for d in self.active_downloaders if d.isRunning()]
    
    #create thumbnail when single image is dropped
    def add_single_thumbnail(self,image_path):
        img=QImage(image_path)
        if not img.isNull():
            scaled_img = img.scaled(150,150,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.add_thumbnail_from_thread(image_path,scaled_img)
    
                
      #for files, check if it's a valid image and add to grid       
    def load_images_from_path(self,folder_path):
        #update tracker when new folder is clicked
        self.active_folder=folder_path
                       
        #wipe current grid
        self.stack.setCurrentWidget(self.grid) #switch to grid view when loading images
        self.grid.clear()
        #if a loader thread is already running, terminate it before starting a new one to prevent multiple threads running at the same time if user quickly loads different folders
        if self.loader_thread is not None and self.loader_thread.isRunning():
            #ask thread to stop
            self.loader_thread.requestInterruption()
            #sever the radio connection so old images don't pop up in the new folder
            self.loader_thread.image_loaded.disconnect()
            
            #put thread into dying
            self.dying_threads.append(self.loader_thread)
            
            #remove threads that died
            self.dying_threads = [t for t in self.dying_threads if t.isRunning()]
            
          

        #Start the background worker for the NEW folder
        self.loader_thread = ImageLoaderThread(folder_path, self.valid_extensions)
        self.loader_thread.image_loaded.connect(self.add_thumbnail_from_thread)
       
        
        #Hook progress bar into thread lifecycle
        self.progress_bar.show()
        self.loader_thread.finished.connect(self.progress_bar.hide)
        self.loader_thread.finished.connect(self.check_if_folder_is_empty)
        self.loader_thread.start()
  
    def load_images_from_list(self,file_paths_list):
        self.active_folder=None
        self.stack.setCurrentWidget(self.grid)
        self.grid.clear()
        #check if images with the tag exist
        if not file_paths_list:
            self.stack.setCurrentWidget(self.no_results_screen)
            return
        #else show the grid
        self.stack.setCurrentWidget(self.grid)
        
        if self.loader_thread is not None and self.loader_thread.isRunning():
            self.loader_thread.requestInterruption()
            self.loader_thread.image_loaded.disconnect()
            self.dying_threads.append(self.loader_thread)
            self.dying_threads=[t for t in self.dying_threads if t.isRunning()]
        
        self.loader_thread = ImageLoaderThread(file_paths_list,self.valid_extensions)
        self.loader_thread.image_loaded.connect(self.add_thumbnail_from_thread)
        
        self.progress_bar.show()
        self.loader_thread.finished.connect(self.progress_bar.hide)
        self.loader_thread.start()       
        
            
    
    def add_thumbnail_from_thread(self, image_path, qimage):
        #convert QImage to QPixmap in the main thread before creating the icon (QPixmap is not thread safe)
        pixmap = QPixmap.fromImage(qimage)
        
        item = QListWidgetItem()
        item.setIcon(QIcon(pixmap))
        item.setData(Qt.ItemDataRole.UserRole, image_path)

        #build tag tooltip with wrapping
        tags = self.db.get_tags_for_image(image_path)
        if tags:
            #group into chunks so it doesnt fill whole screen
            chunked_tags = [", ".join(tags[i:i+5]) for i in range(0,len(tags),5)]
            tag_string=",\n".join(chunked_tags)
            item.setToolTip(f"{os.path.basename(image_path)}\nTags: {tag_string}")
        else:
            item.setToolTip(f"{os.path.basename(image_path)}\n(Tagging in progress...)")    
        
        
        self.grid.addItem(item)    
     
    def stop_threads(self):
        print("Initiating global thread shutdown...")
        
        #Stop active folder loader
        if self.loader_thread is not None  and self.loader_thread.isRunning():
            self.loader_thread.requestInterruption()
            self.loader_thread.wait()

        #Kill dying threads
        if hasattr(self, 'dying_threads'):
            for thread in self.dying_threads:
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.wait()
                    
        #Wait for web downloads to finish 
        if hasattr(self, 'active_downloaders'):
            for downloader in self.active_downloaders:
                if downloader.isRunning():
                    
                    downloader.wait() 
                    
        print("All threads successfully terminated.")
        
    def filter_grid(self,valid_paths):
        #if valid paths is none then search bar is empty so unhide all
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            
            if item is not None:
                if valid_paths is None:
                    item.setHidden(False)
                
                else: 
                    path = item.data(Qt.ItemDataRole.UserRole)
                    #if image path is not in the DB list of matches,then hide it
                    item.setHidden(path not in valid_paths)       