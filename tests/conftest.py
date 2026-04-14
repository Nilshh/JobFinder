"""pytest-Konfiguration: Testumgebung isolieren."""
import os
import tempfile

# Vor allem Import von server.py: DATA_DIR auf Temp-Verzeichnis
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="jobpipeline-test-")
os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
