
import os
import shutil
import json
import urllib.request
from pathlib import Path
from autotagger import AITaggerWorker

#controller for the main canvas area where images are displayed. It also handles drag and drop of folders to add them to the vault.
from PyQt6.QtWidgets import  QDialog,QMessageBox,QCompleter,QInputDialog,QFrame,QMenu,QLineEdit, QHBoxLayout, QListWidgetItem, QMainWindow,QVBoxLayout,QStackedWidget,QLabel,QListWidget, QWidget,QPushButton,QMessageBox,QListView
from PyQt6.QtCore import Qt,QThread,pyqtSignal,QTimer,QStringListModel,QUrl
from canvas import DropCanvas
from database import DatabaseManager
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent,QPixmap,QIcon,QDesktopServices



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
                    
                    #check if app is shutting down
                    if self.isInterruptionRequested():
                        return
                    
                    ext=os.path.splitext(file)[1].lower()
                    if ext in self.valid_extensions:
                        full_path = os.path.join(root,file)
                        
                        #check if DB already knows about the image
                        existing_tags = self.db.get_tags_for_image(full_path)
                        
                        #if db return empty list then it  needs to be tagged
                        if not existing_tags:
                            self.untagged_image_found.emit(full_path)     
        
        print("Crawler finished scanning")


#This class is the lightbox when a image is double clicked it will show the full res image
class LightBox(QDialog):
    def __init__(self,image_path,parent=None):
        super().__init__(parent)
        #borderless 
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint| Qt.WindowType.Dialog)
        self.setModal(True) #Dim the app 
        self.setStyleSheet("background-color:rgba(0,0,0,0.95);")
        
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        self.image_label =QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)
        
        #load original file
        pixmap= QPixmap(image_path)
        
        #get users screen size so imag is not bigger than monitor res
        
        screen=self.screen().availableGeometry() # type: ignore
        scaled_pixmap=pixmap.scaled(
            screen.width()-100,
            screen.height()-100,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    #If user clicks anywhere on the image, it will be closed
    def mousePressEvent(self,event): #type:ignore
        self.accept()
#---------------
#UPdate checker
class UpdateCheckerThread(QThread):
    # Emits the new version string and the download URL if an update is found
    update_available = pyqtSignal(str, str) 

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
       
        self.api_url = "https://api.github.com/repos/ShaheerVD/ArtistReferenceVault/releases/latest"

    def run(self):
        try:
         
            req = urllib.request.Request(self.api_url, headers={'User-Agent': 'ReferenceVault-App'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                
                latest_version = data.get('tag_name', '')
                release_url = data.get('html_url', '')

                #If GitHub's version doesn't match the app's version, trigger the popup
                if latest_version and latest_version != self.current_version:
                    self.update_available.emit(latest_version, release_url)
                    
        except Exception as e:
            #If user have no internet  fail silently so the app still works normally
            print(f"Update check skipped/failed: {e}")



#----------------------------------------------------#
#this class is the main window of the application. It contains the sidebar and the canvas. It listens for signals from the canvas when a folder is dropped and adds it to the sidebar. It also handles clicks on the sidebar to load the corresponding images in the canvas.
class ReferenceVault(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reference Vault")
        self.resize(1000,750)
        icon_path=os.path.join(os.getcwd(),"app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        
        #initialize Core 
        self.master_vault_path = self.setup_master_vault()
        
        self.db = DatabaseManager() 
        
        #update checker
        self.CURRENT_VERSION = "v1.0.2" 
        
        self.update_checker = UpdateCheckerThread(self.CURRENT_VERSION)
        self.update_checker.update_available.connect(self.show_update_dialog)
        self.update_checker.start()
        #Load the Ai model
        self.ai_engine = AITaggerWorker()
        self.ai_engine.tags_generated.connect(self.save_generated_tags)
        self.ai_engine.tags_generated.connect(self.update_image_tooltip)
        self.ai_engine.engine_ready.connect(self.on_ai_ready)
        
        QTimer.singleShot(500, lambda: self.ai_engine.start(QThread.Priority.NormalPriority))
        
        
        self.current_folder_path = None #track the currently loaded folder path to avoid reloading if the same folder is clicked again
        #main window
        self.ai_engine.queue_updated.connect(self.update_ai_status)
        #Base Layout
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
        self.ai_status_label = QLabel("🤖 AI: Sleeping")
        self.ai_status_label.setStyleSheet("color: #2ecc71; padding: 10px; font-weight: bold; background-color: #273746; border-radius: 5px;")
        self.ai_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(self.ai_status_label)
        
        
        
        #add drop canvas for image grid
        self.canvas = DropCanvas(self.db)
        self.canvas.folder_dropped.connect(self.add_folder_to_sidebar)
        
        #When Canvas announces a new Image, put it into the Ai's queue
        self.canvas.image_added.connect(self.ai_engine.queue_image)
        
        #catch distress signal and trigger a popup
        self.canvas.needs_new_folder.connect(self.create_custom_folder)
        
        #connect double click to lightbox
        self.canvas.grid.itemDoubleClicked.connect(self.open_lightbox)
        
        
        #load folders from database and add to sidebar on startup
        self.refresh_sidebar()

       #Search bar
        self.search_bar = QLineEdit()
        self.search_bar.setText("Loading autotagger..please wait")
        self.search_bar.setEnabled(False)
        self.search_bar.setStyleSheet("""
           QLineEdit{
               background-color:#2a2a2a;
               color:white;
               border:1px solid #3d3d3d;
               border-radius:4px;
               padding:8px;
               font-size:14px;
           }                     
           QLineEdit:focus{
               border:1px solid #3498db;
           }      
        """)
        
        #autoComplete for search
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        
        drop_down_menu = QListView()
        drop_down_menu.setStyleSheet("""
            QListView {
                background-color: #2a2a2a; 
                color: white; 
                border: 1px solid #3d3d3d;
            }
            QListView::item:selected {
                background-color: #3498db;
            }
        """)
        self.completer.setPopup(drop_down_menu)
        
        
        self.search_bar.setCompleter(self.completer)
        self.search_bar.textChanged.connect(self.perform_search)

        #hELP BUTTON
        self.help_btn = QPushButton("?")
        self.help_btn.setFixedSize(38, 38)
        self.help_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a; color: #888888;
                border: 1px solid #3d3d3d; border-radius: 4px;
                font-size: 18px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3d3d3d; color: white; }
        """)
        self.help_btn.clicked.connect(self.show_help)

        #LAYOUT
        #Group the Search Bar and Help Button together horizontally
        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.help_btn)
        
        #Stack the Search row directly on top of the Canvas
        right_side_layout = QVBoxLayout()
        right_side_layout.setContentsMargins(0,0,0,0)
        right_side_layout.addLayout(search_layout) 
        right_side_layout.addWidget(self.canvas)
        
        #put the Sidebar on the left, and the Right Side on the right
        main_layout.addWidget(self.sidebar)
        main_layout.addLayout(right_side_layout)
        
       
        
        #Trigger background crawler
        saved_folders = self.db.get_folders()
        folder_paths = [path for name,path in saved_folders] 
        if folder_paths:
            self.start_crawler(folder_paths)
    
    #UI FUNCTIONS----------------------------------------------------------------
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
        remove_ref_action=None
        delete_perm_action = None
        
        if item is not None:
            self.folder_list.setCurrentItem(item) #select the item that was right-clicked
        
            remove_ref_action = menu.addAction("Remove Folder from Vault (Keep Files)")
            delete_perm_action = menu.addAction("Delete Folder Permanently from PC")
        
        
        action = menu.exec(event.globalPos())
        
        if action == add_action:
            self.create_custom_folder()
        elif remove_ref_action and action == remove_ref_action:
            self.remove_folder(item, permanent=False)    
        elif delete_perm_action and action == delete_perm_action:
            self.remove_folder(item, permanent=True)   
        
    
    
    
     
    def remove_folder(self, item,permanent=False):
        path = item.data(Qt.ItemDataRole.UserRole)
        #warning for permanent folder deletion
        if permanent:
            
            reply = QMessageBox.question(
                self, 
                "Permanent Delete", 
                f"Are you sure you want to PERMANENTLY delete the folder '{os.path.basename(path)}' and ALL its images from your PC?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.db.delete_folder(path) #remove from database
        row = self.folder_list.row(item)
        self.folder_list.takeItem(row) #remove from sidebar
        
        if self.current_folder_path == path:
            self.canvas.grid.clear() 
            self.current_folder_path = None 
            self.canvas.stack.setCurrentWidget(self.canvas.welcome_screen) 
            
        #Only invoke shutil if permanent is true
        if permanent:
            try:
                shutil.rmtree(path)
            except Exception as e:
                print(f"Failed to permanently delete folder: {e}")
        self.refresh_sidebar()
    
    
     #sidebar with visual heirarchy   
    def refresh_sidebar(self):
        
        self.folder_list.clear()
        
        saved_folders = self.db.get_folders()
        #Sort by path so subfolders always appear directly under their parents!
        saved_folders.sort(key=lambda x: os.path.normpath(x[1]))
        
        for name, path in saved_folders:
            clean_path = os.path.normpath(path)
            depth = 0
            
            #Calculate how deep this folder is by counting its parents in the DB
            for _, other_path in saved_folders:
                clean_other = os.path.normpath(other_path)
                #If this path is inside another path, increase its depth
                if clean_path != clean_other and clean_path.startswith(clean_other + os.sep):
                    depth += 1
            
            #Apply the visual UI prefix
            if depth == 0:
                display_name = name
            else:
                #add spaces based on depth
                prefix = ("    " * (depth - 1)) + " └─ "
                display_name = prefix + name
                
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.folder_list.addItem(item)
            
            #keep the currently active folder visually selected
            if path == self.current_folder_path:
                self.folder_list.setCurrentItem(item)

        #on app startup, automatically select and load the very first folder
        if not self.folder_list.currentItem() and self.folder_list.count() > 0:
            first_item = self.folder_list.item(0)
            self.folder_list.setCurrentItem(first_item)
            self.current_folder_path = first_item.data(Qt.ItemDataRole.UserRole) #type:ignore
            self.canvas.load_images_from_path(self.current_folder_path)
    
    #add folder to sidebar when dropped and store full path in item data for later use
    def add_folder_to_sidebar(self, folder_name, full_path):
        self.db.add_folder(folder_name, full_path) #save to database
        
        #Update tracker and force the UI to rebuild the tree
        self.current_folder_path = full_path
        self.refresh_sidebar()
        
        #Load the images into the canvas
        self.search_bar.setEnabled(True)
        self.search_bar.clear()
        self.canvas.load_images_from_path(full_path)
        
        #Tell crawler to scan the newly dropped folder
        self.start_crawler([full_path])
       
    #when a folder is clicked in the sidebar, load its images in the canvas
    def on_sidebar_folder_clicked(self, item):
        folder_path = item.data(Qt.ItemDataRole.UserRole) #get full path from item data
        if folder_path != self.current_folder_path: #only reload if different folder is clicked
            self.current_folder_path = folder_path
            self.search_bar.setEnabled(True)
            self.search_bar.clear()
        self.canvas.load_images_from_path(folder_path)
    
    #shutdown function stops the AI and threads
    def closeEvent(self,event): #type:ignore
        print("shutting down...")
        #stop background activity
        self.canvas.stop_threads()
        #kill the AI hahaha
        self.ai_engine.stop_engine()
        #kill crawler thread
        if hasattr(self, 'crawler') and self.crawler.isRunning():
            self.crawler.requestInterruption()
            self.crawler.wait()
        
        event.accept()   
        
    #save generated image tags    
    def save_generated_tags(self,image_path,tags_list):
        for tag in tags_list:
            self.db.add_tag(image_path,tag)    
        self.update_search_autocomplete() #learn new words in real time as ai tags
        
        
    
    def update_image_tooltip(self, image_path, tags_list):
        #Finds the tagged image in the UI grid and updates its hover text
        
        #Format the tags
        chunked_tags = [", ".join(tags_list[i:i+5]) for i in range(0, len(tags_list), 5)]
        tag_string = ",\n".join(chunked_tags)
        new_tooltip = f"{os.path.basename(image_path)}\nTags:\n{tag_string}"
        
        #Loop through the visual grid to find the matching thumbnail
        for i in range(self.canvas.grid.count()):
            item = self.canvas.grid.item(i)
            #Check if this thumbnail's saved path matches the one the AI just finished
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == image_path:
                item.setToolTip(new_tooltip)
                break #Stop searching once updated it    
    
    #function starts the crawler
    def start_crawler(self,folder_paths_list):        
        self.crawler  = BackgroundCrawlerThread(folder_paths_list,self.db)
        
        #Route crawler discoveries directly to the AI inbox
        self.crawler.untagged_image_found.connect(self.ai_engine.queue_image)
        self.crawler.start()
        
    #search with search bar
    def perform_search(self,text):
         
        
        search_term=text.strip().lower()
        
        #if user deletes thier search or types only spaces then show all images
        if not search_term:
            if self.current_folder_path:
                #reselect the folder in the sidebar visually
                for i in range(self.folder_list.count()):
                    item = self.folder_list.item(i)
                    if item is not None and item.data(Qt.ItemDataRole.UserRole) == self.current_folder_path:
                        self.folder_list.setCurrentItem(item)
                        break
                #reload the folder's images
                self.canvas.load_images_from_path(self.current_folder_path)
            else:
                self.canvas.grid.clear()
                self.canvas.stack.setCurrentWidget(self.canvas.welcome_screen)
            return        
            
        
        #ask db for global paths that match the tag
        matching_paths = self.db.global_search_by_tag(search_term)
        #Deselect sidebar visually
        #need to remember where they were so we can return when they clear the search bar
        self.folder_list.clearSelection()
        self.canvas.load_images_from_list(matching_paths)
        
        
    def on_ai_ready(self):
        #clear loading text
        self.search_bar.clear()
        self.search_bar.setPlaceholderText("Search for images here (e.g. 'girl','sword','dynamic pose')...")
        
        if self.current_folder_path:
            self.search_bar.setEnabled(True)    
        self.update_search_autocomplete() #learn new words in real time as ai tags
        print("UI unlocked,ready for search")    
        
    def update_search_autocomplete(self):
        #fetch all known tags from db and give to the search bar
        tags = self.db.get_unique_tags()
        model= QStringListModel(tags)
        self.completer.setModel(model)
    
    
    def open_lightbox(self,item):
        #get file path attatched to a image that is double clicked by the user
        image_path = item.data(Qt.ItemDataRole.UserRole)
        
        if image_path and os.path.exists(image_path):
            #spawn viewer
            viewer =LightBox(image_path,self)
            viewer.exec()        
    
    def show_help(self):
        QMessageBox.information(
            self,
            "Vault Controls & Help",
            "Welcome to Reference Vault!\n\n"
            "• Adding Media: Drag & drop folders from your PC, or drag images directly from your web browser.\n"
            "• Tagging: The app automatically analyzes your images in the background and assigns searchable tags.\n"
            "• Global Search: Type any tag (like 'sword' or 'blue eyes') to instantly find matching images across all folders.\n"
            "• Full-Screen View: Double-click any thumbnail to open the high-resolution lightbox.\n"
            "• Managing Files: Right-click folders in the sidebar or images in the grid to safely remove them or permanently delete them."
        )        
        
    def update_ai_status(self, count):
        #Updates the sidebar to show how many images the AI has left to tag.
        if count > 0:
            self.ai_status_label.setText(f"⚙️ Auto Tagging: {count} left")
            # Turn it yellow to show it's busy working
            self.ai_status_label.setStyleSheet("color: #f1c40f; padding: 10px; font-weight: bold; background-color: #273746; border-radius: 5px;")
        else:
            self.ai_status_label.setText("🤖 Auto Tagger: Ready")
            # Turn it green to show it's done
            self.ai_status_label.setStyleSheet("color: #2ecc71; padding: 10px; font-weight: bold; background-color: #273746; border-radius: 5px;")    
    
     #Displays a popup when a new GitHub release is found.
    def show_update_dialog(self, latest_version, release_url):
       
        reply = QMessageBox.information(
            self,
            "Update Available!",
            f"A new version of Reference Vault ({latest_version}) is available!\n\n"
            f"You are currently running {self.CURRENT_VERSION}.\n\n"
            f"Would you like to download the update now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            #Opens the users default web browser (Chrome/Edge/etc) to the download page
            QDesktopServices.openUrl(QUrl(release_url))         