
import os
import sys


from PyQt6.QtWidgets import QApplication
from window import ReferenceVault

#entry point of the application
if __name__ == "__main__":
    try:
        myappid='burger.referencevault.app.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        pass
    #loop to run the application
    
    
    app = QApplication(sys.argv)
    window = ReferenceVault()
    window.show()
    sys.exit(app.exec())        