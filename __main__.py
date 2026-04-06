try:
    from .tools.chat.cli import main
except ImportError:
    from  tools.chat.cli import main

if __name__ == "__main__":
    main()
