"""Native folder selection runs on the main thread of a separate process."""
import json
import sys


def main():
    import tkinter as tk
    from tkinter.filedialog import askdirectory

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        folder = askdirectory(parent=root, title="Open a project folder", mustexist=True)
        print(json.dumps(folder or ""))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
