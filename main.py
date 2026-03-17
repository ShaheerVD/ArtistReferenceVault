import onnxruntime
import sys
from PyQt6.QtWidgets import QApplication
from window import ReferenceVault



#entry point of the application
if __name__ == "__main__":
    #loop to run the application
    app = QApplication(sys.argv)
    window = ReferenceVault()
    window.show()
    sys.exit(app.exec())        