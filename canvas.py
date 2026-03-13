import os
from PyQt6 import QtCore
from PyQt6.QtWidgets import QFrame, QListWidgetItem,QVBoxLayout,QStackedWidget,QLabel,QListWidget
from PyQt6.QtCore import QSize, QThread, Qt, pyqtSignal,QUrl,QMimeData
from PyQt6.QtGui import QImage, QPixmap,QDrag,QIcon

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
            if self.isInterruptionRequested():
                return
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.valid_extensions:
                    full_path = os.path.join(root, file)
                    
                    #load the image using QImage which is more memory efficient than QPixmap for processing
                    img = QImage(full_path)
                    if not img.isNull():
                        
                        scaled_img = img.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        
                        
                        self.image_loaded.emit(full_path, scaled_img)


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
            

#this class handles the drag and drop of folders onto the canvas and displays the image grid. It emits a signal when a folder is dropped so the main window can add it to the sidebar. It also has a method to load images from a given folder path and display them as thumbnails in the grid.

class DropCanvas(QFrame):
    
    folder_dropped=pyqtSignal(str,str)
    
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
        
    #triggered when the user drops files onto the canvas
    def dropEvent(self, event): # type: ignore
        self.setStyleSheet("background-color: #1e1e1e;color: gray;")
        for url in event.mimeData().urls():
            path=url.toLocalFile()
            #check if file or folder
            if os.path.isdir(path):
                #for folders, emit signal with folder name and path 
                folder_name=os.path.basename(path)
                self.folder_dropped.emit(folder_name,path)
      
      #for files, check if it's a valid image and add to grid       
    def load_images_from_path(self,folder_path):
        #wipe current grid
        self.stack.setCurrentWidget(self.grid) #switch to grid view when loading images
        self.grid.clear()
        #if a loader thread is already running, terminate it before starting a new one to prevent multiple threads running at the same time if user quickly loads different folders
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.requestInterruption()

        #Start the background worker
        self.loader_thread = ImageLoaderThread(folder_path, self.valid_extensions)
        #Connect the worker's signal to our UI update function
        self.loader_thread.image_loaded.connect(self.add_thumbnail_from_thread)
        self.loader_thread.start()
        
        
  
        
    
    def add_thumbnail_from_thread(self, image_path, qimage):
        #convert QImage to QPixmap in the main thread before creating the icon (QPixmap is not thread safe)
        pixmap = QPixmap.fromImage(qimage)
        
        item = QListWidgetItem()
        item.setIcon(QIcon(pixmap))
        item.setData(Qt.ItemDataRole.UserRole, image_path)
        item.setToolTip(os.path.basename(image_path))
        self.grid.addItem(item)    
                