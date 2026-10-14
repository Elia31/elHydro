# Testdaten in einen temporären Ordner statt nach webapp/data/ schreiben. Muss vor dem
# ersten Import aus src/ passieren, weil constants.py den Pfad beim Import festlegt.
import atexit
import os
import shutil
import tempfile

_data_dir = tempfile.mkdtemp(prefix="elhydro-test-")
os.environ["ELHYDRO_DATA_DIR"] = _data_dir
atexit.register(shutil.rmtree, _data_dir, ignore_errors=True)
