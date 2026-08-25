#!/Users/dkisel/PycharmProjects/kiselgram-dev/.venv/bin/python
"""
Kiselgram Management Script
Complete Messaging Platform with Groups, Channels & File Support
"""

import os
import sys
import platform
import time
import webbrowser
import socket
import subprocess
import threading
import signal
import atexit
import json
import logging
import logging.handlers
import secrets
from pathlib import Path
from datetime import datetime

import click

from app import create_app

# Try to import TOML support
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

# Try to import requests for API calls
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Global variables
flask_process = None
video_process = None
is_running = False
STATUS_FILE = 'status/kiselgram.json'
VIDEO_STATUS_FILE = 'status/kiselgram-video.json'
TOKEN_FILE = '.kiselgram_token'

# Logger instances
kiselgram_logger = None
video_logger = None
main_logger = None
kiselgram_log_fh = None
video_log_fh = None
main_log_fh = None


def setup_logging(config=None):
    """Setup logging configuration"""
    global kiselgram_logger, video_logger, main_logger
    global kiselgram_log_fh, video_log_fh, main_log_fh

    log_settings = {
        'kiselgram': {'file': 'kiselgram.log', 'level': 'INFO', 'max_bytes': 10485760, 'backup_count': 5},
        'video': {'file': 'kis_vid.log', 'level': 'INFO', 'max_bytes': 10485760, 'backup_count': 5},
        'main': {'file': 'kis_main.log', 'level': 'INFO', 'max_bytes': 10485760, 'backup_count': 5}
    }

    if config and 'logging' in config:
        if 'kiselgram' in config['logging']:
            log_settings['kiselgram'].update(config['logging']['kiselgram'])
        if 'video' in config['logging']:
            log_settings['video'].update(config['logging']['video'])
        if 'main' in config['logging']:
            log_settings['main'].update(config['logging']['main'])

    Path('logs').mkdir(exist_ok=True)

    log_format = "%(asctime)s - %(name)s - %(levelname)s : %(message)s"
    formatter = logging.Formatter(log_format)

    # Setup kiselgram logger
    kiselgram_logger = logging.getLogger('kiselgram')
    kiselgram_logger.setLevel(getattr(logging, log_settings['kiselgram']['level'].upper()))
    kiselgram_logger.handlers.clear()
    kiselgram_handler = logging.handlers.RotatingFileHandler(
        f"logs/{log_settings['kiselgram']['file']}",
        maxBytes=log_settings['kiselgram']['max_bytes'],
        backupCount=log_settings['kiselgram']['backup_count'],
        encoding='utf-8'
    )
    kiselgram_handler.setFormatter(formatter)
    kiselgram_logger.addHandler(kiselgram_handler)
    kiselgram_log_fh = open(f"logs/{log_settings['kiselgram']['file']}", 'a', encoding='utf-8')

    # Setup video logger
    video_logger = logging.getLogger('video')
    video_logger.setLevel(getattr(logging, log_settings['video']['level'].upper()))
    video_logger.handlers.clear()
    video_handler = logging.handlers.RotatingFileHandler(
        f"logs/{log_settings['video']['file']}",
        maxBytes=log_settings['video']['max_bytes'],
        backupCount=log_settings['video']['backup_count'],
        encoding='utf-8'
    )
    video_handler.setFormatter(formatter)
    video_logger.addHandler(video_handler)
    video_log_fh = open(f"logs/{log_settings['video']['file']}", 'a', encoding='utf-8')

    # Setup main logger
    main_logger = logging.getLogger('main')
    main_logger.setLevel(getattr(logging, log_settings['main']['level'].upper()))
    main_logger.handlers.clear()
    main_handler = logging.handlers.RotatingFileHandler(
        f"logs/{log_settings['main']['file']}",
        maxBytes=log_settings['main']['max_bytes'],
        backupCount=log_settings['main']['backup_count'],
        encoding='utf-8'
    )
    main_handler.setFormatter(formatter)
    main_logger.addHandler(main_handler)
    main_log_fh = open(f"logs/{log_settings['main']['file']}", 'a', encoding='utf-8')

    # Share main logger with app.utils.logging_utils so files.py can use it
    from app.utils.logging_utils import set_main_logger
    set_main_logger(main_logger)

    return True


def log_main(level, message, domain='general'):
    if main_logger:
        getattr(main_logger, level.lower())(f"{domain} - {message}")


def get_shutdown_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    else:
        token = secrets.token_urlsafe(32)
        with open(TOKEN_FILE, 'w') as f:
            f.write(token)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except:
            pass
        return token


SHUTDOWN_TOKEN = get_shutdown_token()


def load_config():
    """Load configuration from kis.toml"""
    config = {}
    config_paths = ['config/kis.toml', 'kis-1.toml']
    config_file = None

    for path in config_paths:
        if os.path.exists(path):
            config_file = path
            break

    if not config_file:
        click.echo("⚠️  Config file not found, using default configuration")
        return create_default_config()

    if tomllib is None:
        click.echo("❌ TOML support not available. Install tomli or use Python 3.11+")
        return create_default_config()

    try:
        with open(config_file, 'rb') as f:
            config = tomllib.load(f)
        click.echo(f"✅ Configuration loaded from {config_file}")
        setup_logging(config)
        return config
    except Exception as e:
        click.echo(f"❌ Error loading config: {e}")
        click.echo("Using default configuration")
        setup_logging()
        return create_default_config()


def create_default_config():
    """Create default configuration file"""
    default_config = r"""# Kiselgram Configuration File

[app]
name = "Kiselgram"
version = "2.0.0"
debug = true
host = "0.0.0.0"
port = 5000
secret_key = "dev-secret-key-change-in-production"

[database]
url = "sqlite:///kiselgram.db"
echo = false

[server]
workers = 4
threaded = true

[video]
enabled = true
host = "0.0.0.0"
port = 5001
quality = "medium"
max_size = 104857600
auto_start = true

[logging]

[logging.kiselgram]
file = "kiselgram.log"
level = "INFO"
max_bytes = 10485760
backup_count = 5

[logging.video]
file = "kis_vid.log"
level = "INFO"
max_bytes = 10485760
backup_count = 5

[logging.main]
file = "kis_main.log"
level = "INFO"
max_bytes = 10485760
backup_count = 5

[telegram]
bot_token = "YOUR_BOT_TOKEN_HERE"
webhook_url = ""

[uploads]
folder = "uploads"
max_size = 16777216
allowed_images = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
allowed_documents = [".pdf", ".doc", ".docx", ".txt", ".md"]
allowed_videos = [".mp4", ".avi", ".mov", ".mkv"]

[features]
groups = true
channels = true
bots = true
video_streaming = true
file_sharing = true
reactions = true

[mail]
server = "mail.kiselgram.ru"
port = 587
username = "Auth@mail.kiselgram.ru"
password = "$uper$ecurePassWo_d"
sender_name = "Kiselgram - Auth"
sender_email = "auth@mail.kiselgram.ru"

[google]
client_id = ""
client_secret = ""
"""

    os.makedirs('config', exist_ok=True)
    with open('config/kis.toml', 'w') as f:
        f.write(default_config)
    click.echo("✅ Created default kis.toml configuration file")
    setup_logging()
    return {'app': {'port': 5000, 'host': '0.0.0.0', 'debug': True},
            'video': {'port': 5001, 'host': '0.0.0.0', 'enabled': True}}


def print_header():
    """Print fancy header"""
    click.echo("\n" + "=" * 74)
    click.echo("  ____      __ __ _________ ________    __________  ___    __  ___   ____")
    click.echo(" / / /     / //_//  _/ ___// ____/ /   / ____/ __ \\/   |  /  |/  /   \\ \\ \\")
    click.echo("/ / /     / ,<   / / \\__ \\/ __/ / /   / / __/ /_/ / /| | / /|_/ /     \\ \\ \\")
    click.echo("\\ \\ \\    / /| |_/ / ___/ / /___/ /___/ /_/ / _, _/ ___ |/ /  / /      / / /")
    click.echo(" \\_\\_\\  /_/ |_/___//____/_____/_____/\\____/_/ |_/_/  |_/_/  /_/      /_/_/")
    click.echo("=" * 74)
    click.echo("📱 Complete Messaging Platform v3.0")
    click.echo("👥 Groups | 📢 Channels | 📁 File Support | 🤖 Bots | 🎥 Video Server")
    click.echo("=" * 74)


def check_dependencies():
    """Check if required dependencies are installed"""
    click.echo("\n📦 Checking dependencies...")
    required = ['flask', 'flask_sqlalchemy', 'dotenv', 'PIL']
    all_installed = True

    for dep in required:
        try:
            __import__(dep.replace('-', '_'))
            click.echo(f"✅ {dep}")
        except ImportError:
            click.echo(f"❌ {dep} - Install with: pip install {dep}")
            all_installed = False

    return all_installed


def check_port_available(port):
    """Check if a port is available"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result != 0
    except:
        return True


def save_status(port, pid, service='main'):
    status_file = VIDEO_STATUS_FILE if service == 'video' else STATUS_FILE
    Path(status_file).parent.mkdir(parents=True, exist_ok=True)
    status = {'running': True, 'port': port, 'pid': pid, 'service': service, 'started_at': datetime.now().isoformat()}
    with open(status_file, 'w') as f:
        json.dump(status, f)


def load_status(service='main'):
    status_file = VIDEO_STATUS_FILE if service == 'video' else STATUS_FILE
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except:
            return None
    return None


def clear_status(service='main'):
    status_file = VIDEO_STATUS_FILE if service == 'video' else STATUS_FILE
    if os.path.exists(status_file):
        os.remove(status_file)


def kill_process_on_port(port):
    """Kill process running on specific port"""
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, shell=True)
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                        click.echo(f"✓ Killed process {pid} on port {port}")
        else:
            try:
                result = subprocess.run(['lsof', '-ti', f':{port}'], capture_output=True, text=True)
                if result.stdout.strip():
                    for pid in result.stdout.strip().split():
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                            time.sleep(0.5)
                            try:
                                os.kill(int(pid), 0)
                                os.kill(int(pid), signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            click.echo(f"✓ Killed process {pid} on port {port}")
                        except:
                            pass
            except FileNotFoundError:
                subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
                click.echo(f"✓ Sent kill signal to processes on port {port}")
    except Exception as e:
        click.echo(f"⚠️ Error killing process on port {port}: {e}")


def stop_application(service='all'):
    """Stop running applications"""
    if service == 'all' or service == 'main':
        status = load_status('main')
        if status:
            port = status.get('port', 5000)
            click.echo(f"🛑 Stopping main app on port {port}...")
            kill_process_on_port(port)
        clear_status('main')
        subprocess.run(['pkill', '-f', 'run_kiselgram.py'], capture_output=True)
        click.echo("✅ Main application stopped")

    if service == 'all' or service == 'video':
        video_status = load_status('video')
        if video_status:
            port = video_status.get('port', 5001)
            click.echo(f"🛑 Stopping video server on port {port}...")
            kill_process_on_port(port)
        clear_status('video')
        subprocess.run(['pkill', '-f', 'run_video_server.py'], capture_output=True)
        click.echo("✅ Video server stopped")

    for tmp_file in ['/tmp/run_kiselgram.py', '/tmp/run_video_server.py']:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except:
                pass

    return True


def run_flask_app(host, port, debug, no_browser=False):
    """Run Flask application"""
    global flask_process, is_running

    if host is None or host == 'None':
        host = '0.0.0.0'
    if port is None or port == 'None':
        port = 5000
    port = int(port)

    try:
        env = os.environ.copy()
        env['FLASK_ENV'] = 'development' if debug else 'production'
        env['KISELGRAM_TOKEN'] = SHUTDOWN_TOKEN

        runner_content = f'''#!/usr/bin/env python3
import sys
import os

project_root = "{os.getcwd()}"
os.chdir(project_root)
sys.path.insert(0, project_root)

from app import create_app, db, socketio
from app.utils.bot_utils import setup_bots
import threading

app = create_app()

def init_database():
    with app.app_context():
        db.create_all()
        setup_bots()
        print("✓ Database initialized")

if __name__ == '__main__':
    init_database()
    print("\\n🚀 Kiselgram is running!")
    print(f"🌐 Access at: http://{'localhost' if host == '0.0.0.0' else host}:{port}")
    print("📝 Press Ctrl+C to stop\\n")
    socketio.run(app, host='{host}', port={port}, debug={debug}, allow_unsafe_werkzeug=True)
'''

        runner_path = '/tmp/run_kiselgram.py'
        with open(runner_path, 'w') as f:
            f.write(runner_content)
        os.chmod(runner_path, 0o755)

        cmd = [sys.executable, runner_path]

        click.echo(f"🚀 Starting Flask on http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
        click.echo(f"🔑 Shutdown token: {SHUTDOWN_TOKEN}")

        flask_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=main_log_fh,
            stderr=kiselgram_log_fh,
            universal_newlines=True,
            bufsize=1,
            cwd=os.getcwd()
        )

        is_running = True
        save_status(port, flask_process.pid, 'main')

        if not no_browser:
            def open_browser():
                time.sleep(2)
                try:
                    webbrowser.open(f"http://localhost:{port}")
                except:
                    pass

            threading.Thread(target=open_browser, daemon=True).start()

        return True

    except Exception as e:
        click.echo(f"❌ Error starting Flask: {e}")
        log_main('ERROR', f'Error starting Flask: {e}', 'flask')
        return False


def run_video_server_process(port=5001, host='0.0.0.0'):
    """Run video server"""
    global video_process

    if host is None or host == 'None':
        host = '0.0.0.0'
    if port is None or port == 'None':
        port = 5001
    port = int(port)

    try:
        env = os.environ.copy()
        env['VIDEO_PORT'] = str(port)
        env['VIDEO_HOST'] = host

        runner_content = f'''#!/usr/bin/env python3
import sys
import os

project_root = "{os.getcwd()}"
os.chdir(project_root)
sys.path.insert(0, project_root)

try:
    from video_server.app import app as video_app, socketio

    if __name__ == '__main__':
        print("\\n🎥 Video Server is running!")
        print(f"🌐 Access at: http://localhost:{port}")
        print("📝 Press Ctrl+C to stop\\n")
        socketio.run(video_app, host='{host}', port={port}, debug=False)
except ImportError:
    print("❌ Video server not found. Make sure video_server/ directory exists.")
'''

        runner_path = '/tmp/run_video_server.py'
        with open(runner_path, 'w') as f:
            f.write(runner_content)
        os.chmod(runner_path, 0o755)

        cmd = [sys.executable, runner_path]

        click.echo(f"🎥 Starting Video Server on http://{host if host != '0.0.0.0' else 'localhost'}:{port}")

        video_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=video_log_fh,
            stderr=kiselgram_log_fh,
            universal_newlines=True,
            bufsize=1,
            cwd=os.getcwd()
        )

        save_status(port, video_process.pid, 'video')
        return True

    except Exception as e:
        click.echo(f"❌ Error starting video server: {e}")
        return False


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------

@click.group()
def cli():
    pass


@cli.command()
@click.option('-p', '--port', type=int, default=None, help='Main app port')
@click.option('-h', '--host', default=None, help='Host to bind to')
@click.option('--debug/--no-debug', default=None, help='Enable/disable debug mode')
@click.option('--no-video', is_flag=True, help='Disable video server')
@click.option('--no-browser', is_flag=True, help="Don't open browser")
@click.option('--video-port', type=int, default=None, help='Video server port')
@click.option('--video-host', default=None, help='Video server host')
def start(port, host, debug, no_video, no_browser, video_port, video_host):
    """Start main app and video server as background services"""
    print_header()

    config = load_config()

    main_port = port or config.get('app', {}).get('port', 5000)
    main_host = host or config.get('app', {}).get('host', '0.0.0.0')
    debug_val = debug if debug is not None else config.get('app', {}).get('debug', True)
    video_port_val = video_port or config.get('video', {}).get('port', 5001)
    video_host_val = video_host or config.get('video', {}).get('host', '0.0.0.0')

    if not check_dependencies():
        click.echo("\n❌ Missing dependencies. Install with: pip install -r requirements.txt")
        raise SystemExit(1)

    if not check_port_available(main_port):
        click.echo(f"\n❌ Port {main_port} is already in use!")
        raise SystemExit(1)

    stop_application('all')
    time.sleep(1)

    main_url = f"http://{main_host if main_host != '0.0.0.0' else 'localhost'}:{main_port}"
    video_url = f"http://{video_host_val if video_host_val != '0.0.0.0' else 'localhost'}:{video_port_val}" if not no_video else "DISABLED"

    click.echo(f"\n🚀 Starting Kiselgram services...")
    click.echo(f"   Main App: {main_url}")
    click.echo(f"   Video Server: {video_url}")
    click.echo(f"   Debug: {debug_val}")
    click.echo(f"   Open Browser: {not no_browser}")
    click.echo("-" * 40)

    flask_thread = threading.Thread(target=run_flask_app, args=(main_host, main_port, debug_val, no_browser), daemon=True)
    flask_thread.start()

    if not no_video:
        time.sleep(2)
        video_thread = threading.Thread(target=run_video_server_process, args=(video_port_val, video_host_val), daemon=True)
        video_thread.start()

    time.sleep(3)

    click.echo("\n" + "=" * 40)
    click.echo("✅ Services started!")
    click.echo(f"🌐 Main App: {main_url}")
    click.echo(f"🔑 Shutdown token: {SHUTDOWN_TOKEN}")
    click.echo("\n🛑 To stop: python manage.py stop")
    click.echo("Press Ctrl+C to exit (services continue running)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n👋 Management script stopped. Services continue running.")
        click.echo(f"   Use 'python manage.py stop' to stop services")


@cli.command()
def stop():
    """Stop all services"""
    print_header()
    click.echo("\n🛑 Stopping all services...")
    stop_application('all')


@cli.command()
@click.option('-p', '--port', type=int, default=None, help='Main app port')
@click.option('-h', '--host', default=None, help='Host to bind to')
@click.option('--no-video', is_flag=True, help='Disable video server')
def restart(port, host, no_video):
    """Restart all services"""
    print_header()
    click.echo("\n🔄 Restarting all services...")
    stop_application('all')
    time.sleep(2)
    # Re-run start logic in-process
    ctx = click.get_current_context()
    ctx.invoke(start, port=port, host=host, debug=None, no_video=no_video,
               no_browser=True, video_port=None, video_host=None)


@cli.command()
def status():
    """Check service status"""
    print_header()
    click.echo("\n📊 Service Status")
    click.echo("-" * 40)
    main_status = load_status('main')
    video_status = load_status('video')

    if main_status:
        click.echo(f"Main App: ✅ RUNNING on port {main_status.get('port')}")
    else:
        click.echo("Main App: ❌ NOT RUNNING")

    if video_status:
        click.echo(f"Video Server: ✅ RUNNING on port {video_status.get('port')}")
    else:
        click.echo("Video Server: ❌ NOT RUNNING")


@cli.command()
def setup():
    """Setup environment (create dirs and default config)"""
    print_header()
    click.echo("\n🔧 Setting up environment...")
    os.makedirs('uploads/images', exist_ok=True)
    os.makedirs('uploads/documents', exist_ok=True)
    os.makedirs('uploads/media', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    os.makedirs('status', exist_ok=True)
    create_default_config()
    click.echo("\n✅ Setup completed!")
    click.echo("Next: pip install -r requirements.txt && python manage.py start")


@cli.command()
def clean():
    """Clean temporary files"""
    print_header()
    click.echo("\n🧹 Cleaning temporary files...")
    for tmp in ['/tmp/run_kiselgram.py', '/tmp/run_video_server.py']:
        if os.path.exists(tmp):
            os.remove(tmp)
    click.echo("✅ Cleanup completed")


@cli.command()
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation')
def reset_db(yes):
    """Delete all data (reset database)"""
    print_header()
    if not yes:
        confirm = click.prompt("\n⚠️ This will DELETE ALL DATA! Type 'yes' to continue", type=str)
        if confirm.lower() != 'yes':
            click.echo("Cancelled")
            return
    for db_file in ['kiselgram.db', 'instance/kiselgram.db']:
        if os.path.exists(db_file):
            os.remove(db_file)
            click.echo(f"✓ Removed {db_file}")
    click.echo("✅ Database reset complete")


@cli.command()
def test():
    """Run basic dependency tests"""
    print_header()
    click.echo("\n🧪 Running tests...")
    if check_dependencies():
        click.echo("✅ All basic tests passed!")
    else:
        click.echo("❌ Some tests failed")


# ---------------------------------------------------------------------------
# Video sub-commands
# ---------------------------------------------------------------------------

@cli.group()
def video():
    """Manage the video server"""
    pass


@video.command()
@click.option('-p', '--port', type=int, default=None, help='Video server port')
@click.option('-h', '--host', default=None, help='Video server host')
def start(port, host):
    """Start only the video server"""
    print_header()
    config = load_config()
    video_port = port or config.get('video', {}).get('port', 5001)
    video_host = host or config.get('video', {}).get('host', '0.0.0.0')

    if not check_port_available(video_port):
        click.echo(f"\n❌ Port {video_port} is already in use!")
        raise SystemExit(1)

    click.echo(f"\n🎥 Starting Video Server...")
    run_video_server_process(video_port, video_host)

    click.echo("\n" + "=" * 40)
    click.echo("✅ Video server started!")
    click.echo(f"🌐 http://{video_host if video_host != '0.0.0.0' else 'localhost'}:{video_port}")
    click.echo("\nPress Ctrl+C to exit (server continues running)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n👋 Exiting. Video server continues running.")


@video.command()
def stop():
    """Stop only the video server"""
    click.echo("\n🛑 Stopping video server...")
    stop_application('video')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def cleanup():
    global kiselgram_log_fh, video_log_fh, main_log_fh
    for fh in [kiselgram_log_fh, video_log_fh, main_log_fh]:
        if fh:
            try:
                fh.close()
            except:
                pass


atexit.register(cleanup)

if __name__ == '__main__':
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n👋 Goodbye!")
    except Exception as e:
        click.echo(f"\n❌ Error: {e}")
        sys.exit(1)
