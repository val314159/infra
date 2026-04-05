try:
    from tools.chat.chat import main
except ImportError:
    from .tools.chat.chat import main

if __name__ == "__main__":
    main()
