#local database

import sqlite3

class DatabaseManager:
    def __init__(self,db_path="vault.db"):
        
        self.conn = sqlite3.connect(db_path,check_same_thread=False) #allow access from multiple threads
        self.create_tables()
        
    def create_tables(self):
        # Create the vault table if it doesn't exist
        cursor = self.conn.cursor()
        #Run only once to create the table 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT UNIQUE NOT NULL
            )
        ''')
        self.conn.commit()    
    
    def add_folder(self,name,path):
        cursor = self.conn.cursor()
        #Insert the folder into the database, ignoring duplicates based on the unique path
        cursor.execute("INSERT OR IGNORE INTO folders (name, path) VALUES (?, ?)", (name, path))
        self.conn.commit()
    
    def get_folders(self):
        #Retrieve all folders from the database
        cursor = self.conn.cursor()    
        cursor.execute("SELECT name, path FROM folders")
        #return tuples of (name, path) for all folders in the database
        return cursor.fetchall()
    
    def delete_folder(self,path):
        cursor = self.conn.cursor()
        #Delete the folder from the database based on the unique path
        cursor.execute("DELETE FROM folders WHERE path = ?", (path,))
        self.conn.commit()