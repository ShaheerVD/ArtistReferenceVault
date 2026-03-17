
import os
from pathlib import Path
from autotagger import AITaggerWorker

#controller for the main canvas area where images are displayed. It also handles drag and drop of folders to add them to the vault.
from PyQt6.QtWidgets import QInputDialog,QFrame,QMenu, QHBoxLayout, QListWidgetItem, QMainWindow,QVBoxLayout,QStackedWidget,QLabel,QListWidget, QWidget
from PyQt6.QtCore import Qt,QThread,pyqtSignal
from canvas import DropCanvas
from database import DatabaseManager
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent



#This class will work in the background and find untagged images when the app is opened
class BackgroundCrawlerThread(QThread):
    #emit the path of an image that needs to be tagged
    untagged_image_found = pyqtSignal(str)
    
    def __init__(self,folders_to_scan,db_manager):
        super().__init__()
        self.folders_to_scan = folders_to_scan
        self.db = db_manager
        self.valid_extensions = ['.jpg','.jpeg','.png','.bmp','.webp']
    
    def run(self):
        print(f"Crawler started scanning {len(self.folders_to_scan)} folder(s) for untagged images..")
       
        for folder_path in self.folders_to_scan:
            for root,dirs,files in os.walk(folder_path):
                for file in files:
                    ext=os.path.splitext(file)[1].lower()
                    if ext in self.valid_extensions:
                        full_path = os.path.join(root,file)
                        
                        #check if DB already knows about the image
                        existing_tags = self.db.get_tags_for_image(full_path)
                        
                        #if db return empty list then it  needs to be tagged
                        if not existing_tags:
                            self.untagged_image_found.emit(full_path)     
        
        print("Crawler finished scanning")


#this class is the main window of the application. It contains the sidebar and the canvas. It listens for signals from the canvas when a folder is dropped and adds it to the sidebar. It also handles clicks on the sidebar to load the corresponding images in the canvas.
class ReferenceVault(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.master_vault_path = self.setup_master_vault()
        
        self.db = DatabaseManager() #initialize the database manager
        #Load the Ai model
        self.ai_engine = AITaggerWorker()
        self.ai_engine.tags_generated.connect(self.save_generated_tags)
        self.ai_engine.start()
        
        
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
        
        #When Canvas announces a new Image, put it into the Ai's queue
        self.canvas.image_added.connect(self.ai_engine.queue_image)
        
        #catch distress signal and trigger a popup
        self.canvas.needs_new_folder.connect(self.create_custom_folder)
        
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.canvas) 
    
        #load folders from database and add to sidebar on startup
        self.load_saved_folders()
    
        #extract paths from the saved folders tuples
        saved_folders = self.db.get_folders()
        folder_paths = [path for name,path in saved_folders] 
        
        if folder_paths:
            self.start_crawler(folder_paths)
    
    
    #create master reference library folder in documents
    def setup_master_vault(self):
        home_dir = str(Path.home())
        vault_path = os.path.join(home_dir,"Documents","ReferenceVault_Library")
        os.makedirs(vault_path,exist_ok=True)
        return vault_path
    
    #create folder
    def create_custom_folder(self):
        folder_name, ok= QInputDialog.getText(self,"New Vault Folder","Enter folder name:")
        
        if ok and folder_name.strip():
            folder_name= folder_name.strip()
            #build path
            new_path = os.path.join(self.master_vault_path,folder_name)
            os.makedirs(new_path,exist_ok=True)
            #add to db and sidebar visually
            self.add_folder_to_sidebar(folder_name,new_path)
            print(f"Created custom vault folder: {new_path}")
        
            #Make ui select the new folder
            #loop through sidebar to find new item just created
            for i in range(self.folder_list.count()):
                item = self.folder_list.item(i)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == new_path:
                    #select visually
                    self.folder_list.setCurrentItem(item)
                    self.current_folder_path=new_path
                    #tell canvas to activate this path
                    self.canvas.load_images_from_path(new_path)
                    break
     
    def contextMenuEvent(self,event:QContextMenuEvent): # type: ignore
        pos = self.folder_list.viewport().mapFromGlobal(event.globalPos()) #type: ignore
        item = self.folder_list.itemAt(pos)
        
        menu = QMenu(self)
        menu.setStyleSheet("background-color: #34495e;color:white;padding:5px;")
        
        #always allow creating a new folder
        add_action = menu.addAction("+ New Folder") 
        menu.addSeparator() #type:ignore
        
        #show delete if right click on folder
        delete_action=None
        if item is not None:
            self.folder_list.setCurrentItem(item) #select the item that was right-clicked
        
            delete_action = menu.addAction("Delete Folder")
        
        
        action = menu.exec(event.globalPos())
        
        if action == add_action:
            self.create_custom_folder()
        elif delete_action and action== delete_action:
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
           
        #tell crawler to scan the newly dropped folder
        self.start_crawler([full_path])
       
    #when a folder is clicked in the sidebar, load its images in the canvas
    def on_sidebar_folder_clicked(self, item):
        folder_path = item.data(Qt.ItemDataRole.UserRole) #get full path from item data
        if folder_path != self.current_folder_path: #only reload if different folder is clicked
            self.current_folder_path = folder_path
        self.canvas.load_images_from_path(folder_path)
    
    #shutdown function stops the AI and threads
    def closeEvent(self,event): #type:ignore
        print("shutting down...")
        #stop background activity
        self.canvas.stop_threads()
        #kill the AI hahaha
        self.ai_engine.stop_engine()
        event.accept()   
        
    #save generated image tags    
    def save_generated_tags(self,image_path,tags_list):
        for tag in tags_list:
            self.db.add_tag(image_path,tag)    
     
    
    #function starts the crawler
    def start_crawler(self,folder_paths_list):        
        self.crawler  = BackgroundCrawlerThread(folder_paths_list,self.db)
        
        #Route crawler discoveries directly to the AI inbox
        self.crawler.untagged_image_found.connect(self.ai_engine.queue_image)
        self.crawler.start()