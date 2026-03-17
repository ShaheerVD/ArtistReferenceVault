import os
import shutil #copy local files
import urllib.request #download web files
import uuid #generate unique filename for web images
from PyQt6 import QtCore
from PyQt6.QtWidgets import QFrame, QMenu,QListWidgetItem,QVBoxLayout,QStackedWidget,QMessageBox,QLabel,QListWidget,QProgressBar
from PyQt6.QtCore import QSize, QThread, Qt, pyqtSignal,QUrl,QMimeData
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap,QDrag,QIcon,QContextMenuEvent

#multi threading to stop UI freezing when loading large folders

class ImageLoaderThread(QThread):
    image_loaded=pyqtSignal(str, QImage)
    
    def __init__(self,folder_path,valid_extensions):
        super().__init__()
        self.folder_path=folder_path
        self.valid_extensions=valid_extensions
        
    def run(self):
        for root, dirs, files in os.walk(self.folder_path):
            
            #check for interruption request and stop the thread
            
            for file in files:
                #check to stop itself before loading files to prevent overloading cpu if user rapid clicks between folders (i did it to test and my pc lagged like crazy)
                if self.isInterruptionRequested():
                    return
                ext = os.path.splitext(file)[1].lower()
                if ext in self.valid_extensions:
                    full_path = os.path.join(root, file)
                    
                    #load the image using QImage which is more memory efficient than QPixmap for processing
                    img = QImage(full_path)
                    if not img.isNull():
                        
                        scaled_img = img.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        
                        
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
            delete_text=f"Delete Image" if selected_count==1 else f"Delete{selected_count} Images"
            
            delete_action = menu.addAction(delete_text)
            action = menu.exec(event.globalPos())
            
            if action==delete_action:
                self.remove_selected_images()  
        
        def remove_selected_images(self):
            items_to_delete = self.selectedItems()
            
            #safety net
            reply=QMessageBox.question(
                self,
                "Delete Images",
                f"Are you sure you want to PERMANENTLY delete {len(items_to_delete)} file(s)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                #iterate backwards
                for item in reversed(items_to_delete):
                    path= item.data(Qt.ItemDataRole.UserRole)
                    try:
                        os.remove(path)
                        row=self.row(item)
                        self.takeItem(row)
                    except Exception as e:
                        print(f"Error deleting file {path}: {e}")      
                
#this class handles the drag and drop of folders onto the canvas and displays the image grid. It emits a signal when a folder is dropped so the main window can add it to the sidebar. It also has a method to load images from a given folder path and display them as thumbnails in the grid.

class DropCanvas(QFrame):
    #announce a folder dropped, new image path
    folder_dropped=pyqtSignal(str,str)
    image_added = pyqtSignal(str)
    needs_new_folder = pyqtSignal()
    #canvas for image grid
    def __init__(self):
        super().__init__()
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
            "1. Drag and drop a folder of images anywhere into this window.\n"
            "2. Click the folder name on the left to view your references.\n"
        )
        self.welcome_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_screen.setStyleSheet("color: #888888; font-size: 18px;")
        
        
        #thumbnail grid
        self.grid = ReferenceGrid()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QtCore.QSize(150, 150))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setSpacing(10)
        self.grid.setStyleSheet("QListWidget { border: none; background-color: transparent; }")
        self.stack.addWidget(self.welcome_screen)
        self.stack.addWidget(self.grid)
        
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
                    folder_name = os.path.basename(path)
                    self.folder_dropped.emit(folder_name, path) #emit signal to add folder to sidebar
                
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
        self.loader_thread.start()
  
        
    
    def add_thumbnail_from_thread(self, image_path, qimage):
        #convert QImage to QPixmap in the main thread before creating the icon (QPixmap is not thread safe)
        pixmap = QPixmap.fromImage(qimage)
        
        item = QListWidgetItem()
        item.setIcon(QIcon(pixmap))
        item.setData(Qt.ItemDataRole.UserRole, image_path)
        item.setToolTip(os.path.basename(image_path))
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