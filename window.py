
import os
import shutil
import json
import urllib.request
from pathlib import Path
from autotagger import AITaggerWorker

#controller for the main canvas area where images are displayed. It also handles drag and drop of folders to add them to the vault.
from PyQt6.QtWidgets import  QStyle,QDialog,QMessageBox,QCompleter,QInputDialog,QFrame,QMenu,QLineEdit, QHBoxLayout, QListWidgetItem, QMainWindow,QVBoxLayout,QStackedWidget,QLabel,QListWidget, QWidget,QPushButton,QMessageBox,QListView,QTreeWidget,QTreeWidgetItem,QTreeWidgetItemIterator
from PyQt6.QtCore import Qt,QThread,pyqtSignal,QTimer,QStringListModel,QUrl
from canvas import DropCanvas
from database import DatabaseManager
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent,QPixmap,QIcon,QDesktopServices
from PIL import Image


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
                        
                        #Don't send corrupted files to the AI
                        if os.path.getsize(full_path) > 0:
                            try:
                                with Image.open(full_path) as verify_img:
                                    verify_img.verify()
                            except Exception:
                                print(f"Crawler blocked corrupted AI file: {full_path}")
                                continue
                        else:
                            continue
                        
                        
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
        self.CURRENT_VERSION = "v1.0.4" 
        
        self.update_checker = UpdateCheckerThread(self.CURRENT_VERSION)
        self.update_checker.update_available.connect(self.show_update_dialog)
        self.update_checker.start()
        #Load the Ai model
        self.ai_engine = AITaggerWorker()
        
        #fix ui freezing
        self.tag_buffer = []
        self.db_commit_timer = QTimer()
        self.db_commit_timer.timeout.connect(self.process_tag_buffer)
        self.db_commit_timer.start(2000) # Tick every 2 seconds
        
        self.ai_engine.tags_generated.connect(self.save_generated_tags)
       
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
        
        #collapsible Tree Sidebar
        self.folder_list = QTreeWidget()
        self.folder_list.setHeaderHidden(True)
        self.folder_list.setDragEnabled(True)
        self.folder_list.setAcceptDrops(True)
        self.folder_list.setDropIndicatorShown(True)
        self.folder_list.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        
        self.folder_list.setStyleSheet("""
            QTreeWidget {
                border: none;
                font-size: 14px;
                background-color: #2c3e50;
                color: white;
            }
            QTreeWidget::item {
                padding: 5px;
            }
            QTreeWidget::item:selected {
                background-color: #34495e;
            }
        """)
        #connect folder click to load images in canvas
        self.folder_list.itemClicked.connect(self.on_sidebar_folder_clicked)
        sidebar_layout.addWidget(self.folder_list)
        
        self.folder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.on_folder_context_menu)
        
        #Show ai status on UI
        self.ai_status_label = QLabel("🤖 Auto Tagger: Sleeping")
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
        
        self.canvas.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.grid.customContextMenuRequested.connect(self.on_image_context_menu)
        
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
    def create_custom_folder(self,parent_path=None):
        # If user didn't right-click a specific folder, default to the master vault root
        if parent_path is None:
            parent_path = self.master_vault_path
        
        folder_name, ok= QInputDialog.getText(self,"New Vault Folder","Enter folder name:")
        
        if ok and folder_name.strip():
            folder_name= folder_name.strip()
            #build path inside the selected parent folder
            new_path = os.path.join(parent_path, folder_name)
            os.makedirs(new_path, exist_ok=True)
            #add to db and sidebar visually
            self.add_folder_to_sidebar(folder_name,new_path)
            print(f"Created custom vault folder: {new_path}")
        
            #Make ui select the new folder
            #loop through sidebar to find new item just created
            iterator = QTreeWidgetItemIterator(self.folder_list)
            while iterator.value():
                item = iterator.value()
                if item.data(0, Qt.ItemDataRole.UserRole) == new_path: #type:ignore
                    self.folder_list.setCurrentItem(item)
                    self.current_folder_path = new_path
                    self.canvas.load_images_from_path(new_path)
                    break
                iterator += 1
     
    def on_folder_context_menu(self, pos):
        item = self.folder_list.itemAt(pos)
        
        menu = QMenu(self)
        menu.setStyleSheet("background-color: #34495e;color:white;padding:5px;")
        
        add_action = menu.addAction("+ New Folder") 
        menu.addSeparator() 
        
        rename_action = None
        retag_action=None
        remove_ref_action = None
        delete_perm_action = None
        
        if item is not None:
            self.folder_list.setCurrentItem(item)
            rename_action = menu.addAction("Rename Folder")
            retag_action =menu.addAction("Re-Tag Images")
            menu.addSeparator()
            remove_ref_action = menu.addAction("Remove Folder from Vault (Keep Files)")
            delete_perm_action = menu.addAction("Delete Folder Permanently from PC")
            
        action = menu.exec(self.folder_list.viewport().mapToGlobal(pos)) #type:ignore
        
        if action is None:
            return
            
        if action == add_action:
            if item is not None:
                self.create_custom_folder(parent_path=item.data(0, Qt.ItemDataRole.UserRole))
            else:
                self.create_custom_folder()
                
        elif item is not None: 
            if action == rename_action:  
                old_path = item.data(0, Qt.ItemDataRole.UserRole)
                old_name = item.text(0)
                new_name, ok = QInputDialog.getText(self, "Rename Folder", "Enter new folder name:", text=old_name)
                if ok and new_name.strip() and new_name != old_name:
                    new_name = new_name.strip()
                    parent_dir = os.path.dirname(old_path)
                    new_path = os.path.join(parent_dir, new_name)
                    try:
                        os.rename(old_path, new_path)
                        self.db.rename_folder(old_path, new_path, new_name)
                        self.current_folder_path = new_path
                        self.refresh_sidebar()
                        self.canvas.load_images_from_path(new_path)
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Could not rename folder.\n\n{e}")
             
            elif action == retag_action:
                folder_path = item.data(0, Qt.ItemDataRole.UserRole)
                self.retag_folder(folder_path)            
            elif action == remove_ref_action:
                self.remove_folder(item, permanent=False)    
            elif action == delete_perm_action:
                self.remove_folder(item, permanent=True)   
        
    
    
    
     
    def remove_folder(self, item,permanent=False):
        path = item.data(0, Qt.ItemDataRole.UserRole)
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
        #row = self.folder_list.row(item)
        #self.folder_list.takeItem(row) #remove from sidebar
        
        if self.current_folder_path == path:
            self.canvas.grid.clear() 
            self.current_folder_path = None 
            self.canvas.stack.setCurrentWidget(self.canvas.welcome_screen) 
            
        #Only invoke shutil if permanent is true
        if permanent:
            try:
                import shutil
                shutil.rmtree(path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not delete folder from hard drive. It might be open in another program.\n\n{e}")
        self.refresh_sidebar()
    
    
     #sidebar with visual heirarchy   
    def refresh_sidebar(self):
        
        self.folder_list.clear()
        saved_folders = self.db.get_folders()
        
        #sort paths so parents are processed before their children
        saved_folders.sort(key=lambda x: os.path.normpath(x[1]))
        item_map = {}
        
        for name, path in saved_folders:
            clean_path = os.path.normpath(path)
            parent_path = os.path.dirname(clean_path)
            
            #create the UI node
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            
            folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon) #type:ignore
            item.setIcon(0, folder_icon)
            
            #if the parent path exists, attach this as a child
            if parent_path in item_map:
                parent_item = item_map[parent_path]
                parent_item.addChild(item)
            else:
                self.folder_list.addTopLevelItem(item)
                
            item_map[clean_path] = item
            
            #keep active folder selected
            if path == self.current_folder_path:
                self.folder_list.setCurrentItem(item)
        #force tree to stay expanded 
        self.folder_list.expandAll()       
        #on app startup, automatically select the first folder
        if not self.folder_list.currentItem() and self.folder_list.topLevelItemCount() > 0:
            first_item = self.folder_list.topLevelItem(0)
            self.folder_list.setCurrentItem(first_item)
            self.current_folder_path = first_item.data(0, Qt.ItemDataRole.UserRole) #type:ignore
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
        folder_path = item.data(0,Qt.ItemDataRole.UserRole) #get full path from item data
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
        
    #get the signal and keep it in RAM   
    def save_generated_tags(self,image_path,tags_list):
        self.tag_buffer.append((image_path, tags_list))
    
    #process buffer every 2 seconds    
    def process_tag_buffer(self):
        if not self.tag_buffer:
            return
            
        #save the current batch and clear the list so the AI can keep working
        batch_to_process = self.tag_buffer[:]
        self.tag_buffer.clear()
        
        #save to DB in one big chunk
        self.db.batch_add_tags(batch_to_process)
        
        #safely update the UI tooltips in bulk
        for image_path, tags_list in batch_to_process:
            self.update_image_tooltip(image_path, tags_list)
            
        #rebuild the search autocomplete ONLY once per batch, not per image
        self.update_search_autocomplete()
        print(f"Batch saved {len(batch_to_process)} images to database smoothly.")
     
        
    
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
                #use Tree Iterator to reselect the folder visually ---
                iterator = QTreeWidgetItemIterator(self.folder_list)
                while iterator.value():
                    item = iterator.value()
                   
                    if item.data(0, Qt.ItemDataRole.UserRole) == self.current_folder_path: #type:ignore
                        self.folder_list.setCurrentItem(item)
                        break
                    iterator += 1
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
            "• Adding Media: Drag & drop folders from your PC into the main canvas.\n"
            "• Folder Management: The sidebar matches your PC's folder hierarchy. Right-click any folder to rename it or remove it.\n"
            "• Auto-Tagging: The AI analyzes your images in the background and assigns searchable tags.\n"
            "• Manual Tag Editing: Right-click any image in the grid to manually edit or add custom tags.\n"
            "• Global Search: Type any tag (like 'sword' or 'dynamic pose') to instantly find matching images.\n"
            "• Full-Screen View: Double-click any thumbnail to open the high-resolution lightbox."
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
    #spawns a right-click menu when clicking an image in the grid      
    #spawns a right-click menu when clicking an image in the grid      
    def on_image_context_menu(self, pos):
        item = self.canvas.grid.itemAt(pos)
        if item is None:
            return

        # Handle multi-selection: if they right-click an unselected item, select only that item
        if not item.isSelected():
            self.canvas.grid.clearSelection()
            item.setSelected(True)
            
        selected_items = self.canvas.grid.selectedItems()
        selected_count = len(selected_items)

        menu = QMenu(self)
        menu.setStyleSheet("background-color: #34495e; color: white; padding: 5px;")
        
        # Only show "Edit Tags" if a single image is selected
        edit_tags_action = None
        if selected_count == 1:
            edit_tags_action = menu.addAction("Edit Tags")
            menu.addSeparator()
            
        remove_ref_action = menu.addAction(f"Remove {selected_count} Reference(s) from Vault")
        delete_perm_action = menu.addAction(f"Delete {selected_count} File(s) Permanently from PC")

        #spawn the menu exactly where the mouse is
        action = menu.exec(self.canvas.grid.viewport().mapToGlobal(pos)) #type:ignore
        
        if edit_tags_action and action == edit_tags_action:
            self.edit_image_tags(item)
        elif action == remove_ref_action:
            self.delete_selected_images(selected_items, permanent=False)
        elif action == delete_perm_action:
            self.delete_selected_images(selected_items, permanent=True)


    def delete_selected_images(self, items_to_delete, permanent=False):
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
        #Setup a safe "Eviction" folder in the user's Documents for soft-deleted files
        removed_dir = os.path.join(str(Path.home()), "Documents", "ReferenceVault_Removed")
        if not permanent:
            os.makedirs(removed_dir, exist_ok=True)
        # Iterate backwards so removing items from the UI doesn't shift the index
        for item in reversed(items_to_delete):
            image_path = item.data(Qt.ItemDataRole.UserRole)
            
            #Delete from Database
            try:
                self.db.delete_image(image_path) 
            except AttributeError:
                print("Warning: delete_image method missing in database.py")
                
            #Delete from Windows Hard Drive
            if permanent:
                try:
                    os.remove(image_path)
                except Exception as e:
                    print(f"Error permanently deleting file {image_path}: {e}")
            else:
                #MOVE the file completely out of the monitored Vault folder
                try:
                    filename = os.path.basename(image_path)
                    dest_path = os.path.join(removed_dir, filename)
                    
                    #If user already removed a file with this exact name, add a random string so it doesn't overwrite
                    if os.path.exists(dest_path):
                        import uuid
                        name, ext = os.path.splitext(filename)
                        dest_path = os.path.join(removed_dir, f"{name}_{uuid.uuid4().hex[:6]}{ext}")
                    
                    shutil.move(image_path, dest_path)
                except Exception as e:
                    print(f"Error moving file out of vault {image_path}: {e}")
                    
            #Delete from UI visually
            row = self.canvas.grid.row(item)
            self.canvas.grid.takeItem(row)

    def edit_image_tags(self, item):
        """Pulls current tags, lets the user edit them, and saves to DB."""
        image_path = item.data(Qt.ItemDataRole.UserRole) # QListWidget uses 1 arg!
        
        #get current tags from DB and convert to a comma-separated string
        current_tags = self.db.get_tags_for_image(image_path)
        current_tags_str = ", ".join(current_tags)
        
        #spawn popup window
        new_tags_str, ok = QInputDialog.getText(
            self, 
            "Edit Image Tags", 
            "Edit tags (comma separated):", 
            text=current_tags_str
        )
        
        if ok:
            #clean up the user's input (remove extra spaces and make lowercase)
            raw_tags = new_tags_str.split(',')
            new_tags = [t.strip().lower() for t in raw_tags if t.strip()]
            
            #update Database
            self.db.update_image_tags(image_path, new_tags)
            
            #update the hover Tooltip visually
            self.update_image_tooltip(image_path, new_tags)
            self.update_search_autocomplete()
            
    #This function warns the user then deletes all existing tags for that folder from the database
    #loops through the folder and puts the images back into the Ai's queue        
    def retag_folder(self, folder_path):
        reply = QMessageBox.question(
            self,
            "Re-Tag Folder",
            "This will clear all current tags (including manual ones) for images in this folder and send them back to the AI.\n\nDo you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            valid_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.webp']
            images_queued = 0
            
            #find all images in this folder (and its subfolders)
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_extensions:
                        full_path = os.path.join(root, file)
                        
                        #wipe the old tags from the Database
                        try:
                            self.db.delete_image(full_path)
                        except AttributeError:
                            pass
                            
                        #queue it back into the AI engine
                        self.ai_engine.queue_image(full_path)
                        images_queued += 1
                        
            if images_queued > 0:
                print(f"Sent {images_queued} images to the AI Tagger.")
                
                #refresh the visual canvas to clear the tooltips immediately
                if self.current_folder_path and self.current_folder_path.startswith(folder_path):
                    self.canvas.load_images_from_path(self.current_folder_path)
            else:
                QMessageBox.information(self, "Empty", "No valid images found in this folder.")