#controller for the main canvas area where images are displayed. It also handles drag and drop of folders to add them to the vault.
from PyQt6.QtWidgets import QFrame,QMenu, QHBoxLayout, QListWidgetItem, QMainWindow,QVBoxLayout,QStackedWidget,QLabel,QListWidget, QWidget
from PyQt6.QtCore import Qt
from canvas import DropCanvas
from database import DatabaseManager
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent
#this class is the main window of the application. It contains the sidebar and the canvas. It listens for signals from the canvas when a folder is dropped and adds it to the sidebar. It also handles clicks on the sidebar to load the corresponding images in the canvas.
class ReferenceVault(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager() #initialize the database manager
        self.current_folder_path = None #track the currently loaded folder path to avoid reloading if the same folder is clicked again
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
        self.folder_list.setStyleSheet("""
            QListWidget {
                border: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 10px;
            }
            QListWidget::item:selected {
                background-color: #34495e;
            }
            """)
        #connect folder click to load images in canvas
        self.folder_list.itemClicked.connect(self.on_sidebar_folder_clicked)
        
      
        
        
        sidebar_layout.addWidget(self.folder_list)

        #add drop canvas for image grid
        self.canvas = DropCanvas()
        self.canvas.folder_dropped.connect(self.add_folder_to_sidebar)
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.canvas) 
    
        #load folders from database and add to sidebar on startup
        self.load_saved_folders()
     
    def contextMenuEvent(self,event:QContextMenuEvent): # type: ignore
        pos = self.folder_list.viewport().mapFromGlobal(event.globalPos()) #type: ignore
        item = self.folder_list.itemAt(pos)
        if item is None:return
        
        self.folder_list.setCurrentItem(item) #select the item that was right-clicked
        menu = QMenu(self)
        menu.setStyleSheet("background-color: #34495e; color: white; padding:5px;")
        delete_action = menu.addAction("Delete Folder")
        action = menu.exec(event.globalPos())
        
        if action == delete_action:
         self.remove_folder(item)
        
    
    
    
     
    def remove_folder(self, item):
        path= item.data(Qt.ItemDataRole.UserRole) #get full path from item data
        self.db.delete_folder(path) #remove from database
        row = self.folder_list.row(item)
        self.folder_list.takeItem(row) #remove from sidebar
        
        if self.current_folder_path == path:
            self.canvas.grid.clear() #clear canvas if the currently loaded folder was deleted
            self.current_folder_path = None #reset tracker
            self.canvas.stack.setCurrentWidget(self.canvas.welcome_screen) 
    
    
    
        
    def load_saved_folders(self):
        saved_folders = self.db.get_folders()
        for name, path in saved_folders:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, path) #store full path in item data
            self.folder_list.addItem(item) 
        #if there are saved folders, automatically load the first one in the canvas and update the tracker
        if saved_folders:
            first_item = self.folder_list.item(0)
            self.folder_list.setCurrentItem(first_item)
            self.current_folder_path = first_item.data(Qt.ItemDataRole.UserRole) # type: ignore
            self.canvas.load_images_from_path(self.current_folder_path)
    
    #add folder to sidebar when dropped and store full path in item data for later use
    def add_folder_to_sidebar(self, folder_name, full_path):
        self.db.add_folder(folder_name, full_path) #save to database
        
        item = QListWidgetItem(folder_name)
        #store the full path in the item data for later use when clicked
        item.setData(Qt.ItemDataRole.UserRole, full_path) 
        self.folder_list.addItem(item) 
        
        #when a folder is added, automatically load it in the canvas and switch to canvas view
        if self.folder_list.count()==1:
          
            #select and load first folder and update the tracker
            self.folder_list.setCurrentItem(item)
            self.current_folder_path = full_path
            self.canvas.load_images_from_path(full_path)
           
   
       
    #when a folder is clicked in the sidebar, load its images in the canvas
    def on_sidebar_folder_clicked(self, item):
        folder_path = item.data(Qt.ItemDataRole.UserRole) #get full path from item data
        if folder_path != self.current_folder_path: #only reload if different folder is clicked
            self.current_folder_path = folder_path
        self.canvas.load_images_from_path(folder_path)
       