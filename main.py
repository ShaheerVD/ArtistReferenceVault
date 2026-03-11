import sys
import PyQt6 
import os
from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication, QListWidget,QMainWindow,QLabel, QStackedWidget,QVBoxLayout,QWidget,QHBoxLayout,QPushButton,QFrame,QLabel,QListWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap,QIcon

#drag and drop images onto the canvas to add them to the vault
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
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QtCore.QSize(150, 150))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setSpacing(10)
        self.grid.setStyleSheet("QListWidget { border: none; background-color: transparent; }")
        self.stack.addWidget(self.welcome_screen)
        self.stack.addWidget(self.grid)
        
        
      
        
        #allowed image formats
        self.valid_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.webp']
    
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
        for root,dirs,files in os.walk(folder_path):
            for file in files:
                #get file extension and check if it's a valid image format and make lowercase for comparison
                ext=os.path.splitext(file)[1].lower()
                if ext in self.valid_extensions:
                    full_path=os.path.join(root,file)
                    self.add_thumbnail(full_path)
        
        
  
        
    
    def add_thumbnail(self, image_path):
        #load into memory
        pixmap=QPixmap(image_path)
        
        #downscale to thumbnail size
        scaled_pixmap=pixmap.scaled(150,150,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        #create list item with thumbnail
        item=QListWidgetItem()
        item.setIcon(QIcon(scaled_pixmap))
        #store high res image path
        item.setData(Qt.ItemDataRole.UserRole, image_path) #store full path in item data for later use when clicked
        item.setToolTip(os.path.basename(image_path)) #show image name on hover
        self.grid.addItem(item)    
    
class ReferenceVaul(QMainWindow):
    def __init__(self):
        super().__init__()
        
        #main window
        self.setWindowTitle("Reference Vault")
        self.resize(1000,700)
        
        #central contaainer and horizontal layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        #remove margins and spacing
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        #sidebar for folders and tags
        self.sidebar=QFrame()
        self.sidebar.setFixedWidth(250)
        self.sidebar.setStyleSheet("background-color: #2c3e50;color: white;")
        sidebar_layout = QVBoxLayout(self.sidebar)
        #list for folders
        self.folder_list=QListWidget()
        self.folder_list.setStyleSheet("QListWidget{border: none;font-size:14px;QListWidget::item{padding:10px;QListWidget::item:selected{background-color:#34495e;}}}")
        #connect folder click to load images in canvas
        self.folder_list.itemClicked.connect(self.on_sidebar_folder_clicked)
        
        sidebar_layout.addWidget(self.folder_list)

        #add drop canvas for image grid
        self.canvas = DropCanvas()
        self.canvas.folder_dropped.connect(self.add_folder_to_sidebar)
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.canvas) 
    
    #add folder to sidebar when dropped and store full path in item data for later use
    def add_folder_to_sidebar(self, folder_name, full_path):
        item = QListWidgetItem(folder_name)
        #store the full path in the item data for later use when clicked
        item.setData(Qt.ItemDataRole.UserRole, full_path) 
        self.folder_list.addItem(item) 
        
        #when a folder is added, automatically load it in the canvas and switch to canvas view
        if self.folder_list.count()==1:
          
            #select and load first folder
            self.folder_list.setCurrentItem(item)
            self.canvas.load_images_from_path(full_path)
           
   
       
    #when a folder is clicked in the sidebar, load its images in the canvas
    def on_sidebar_folder_clicked(self, item):
        folder_path = item.data(Qt.ItemDataRole.UserRole) #get full path from item data
        self.canvas.load_images_from_path(folder_path)
       

if __name__ == "__main__":
    #loop to run the application
    app = QApplication(sys.argv)
    window = ReferenceVaul()
    window.show()
    sys.exit(app.exec())        