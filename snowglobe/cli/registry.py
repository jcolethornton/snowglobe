COMMANDS = {}

def command(name):
    def decorator(fn):
        COMMANDS[name] = fn
        return fn
    return decorator
