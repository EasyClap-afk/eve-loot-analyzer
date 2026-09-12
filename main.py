import logging
import sys
from logging.handlers import RotatingFileHandler
from PySide6.QtWidgets import QApplication
from app.storage import Store,data_dir
from app.engine import Engine
from app.esi import Esi
from app.ui import MainWindow,STYLE

def main():
    handler=RotatingFileHandler(data_dir()/'analyzer.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    logging.basicConfig(level=logging.WARNING,handlers=[handler],format='%(asctime)s %(levelname)s %(message)s')
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    store=Store();window=MainWindow(store,Engine(store,Esi(store)));window.show()
    return app.exec()

if __name__=='__main__':sys.exit(main())
