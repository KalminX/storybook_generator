#!/usr/bin/env python
"""Entry point for the Storybook Generator Web App."""

import os
import sys
import threading
import time
import webbrowser

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'storybook_web.settings')
    
    from django.core.management import execute_from_command_line, call_command
    import django

    django.setup()

    # Automatically run migrations for sqlite
    print("Preparing Storybook Studio database...")
    call_command('migrate', '--no-input', verbosity=0)

    port = os.environ.get("PORT", "8000")
    host = "127.0.0.1"
    url = f"http://{host}:{port}/"

    def open_browser():
        time.sleep(1.2)
        print(f"\n✨ Storybook Studio is running at: {url}\nOpening your browser...\n")
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    sys.argv = ['manage.py', 'runserver', f'{host}:{port}']
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
