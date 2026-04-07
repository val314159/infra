try:
    from .chat.chat import main
except ImportError:
    from chat.chat import main

if __name__ == "__main__":
    main()
