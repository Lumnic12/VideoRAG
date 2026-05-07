import sys
import os

# Unbuffered print
def unbuffered_print(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()

unbuffered_print("Starting script...")

class TraceImporter:
    def find_module(self, fullname, path=None):
        unbuffered_print(f"Importing: {fullname}")
        return None

sys.meta_path.insert(0, TraceImporter())

unbuffered_print("About to import main...")
try:
    import main
    unbuffered_print("MAIN IMPORTED SUCCESSFULLY!")
except Exception as e:
    unbuffered_print(f"FAILED: {e}")
