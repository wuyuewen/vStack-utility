'''

@author: frank
'''
from zstacklib.utils import plugin
from zstacklib.utils import http
from zstacklib.utils import log
from zstacklib.utils import jsonobject
from zstacklib.utils import daemon
from zstacklib.utils import linux
import os.path
import atexit
import time
import traceback
import pprint
import functools
import sys


logger = log.get_logger(__name__)

class AliyunError(Exception):
    '''aliyun error'''
    
class AliyunAgent(plugin.Plugin):
    '''
    classdocs
    '''
    
    def __init__(self):
        '''
        Constructor
        '''
        pass

_rest_service = None
_qemu_path = None

def new_rest_service(config={}):
    global _rest_service
    if not _rest_service:
        _rest_service = AliyunRESTService(config)
    return _rest_service

def get_http_server():
    return _rest_service.http_server

def get_qemu_path():
    global _qemu_path
    if not _qemu_path:
        if os.path.exists('/usr/libexec/qemu-kvm'):
            _qemu_path = '/usr/libexec/qemu-kvm'
        elif os.path.exists('/bin/qemu-kvm'):
            _qemu_path = '/bin/qemu-kvm'
        elif os.path.exists('/usr/bin/qemu-system-x86_64'):
            # ubuntu
            _qemu_path = '/usr/bin/qemu-system-x86_64'
        else:
            raise AliyunError('Could not find qemu-kvm in /bin/qemu-kvm or /usr/libexec/qemu-kvm or /usr/bin/qemu-system-x86_64')

    return _qemu_path
        
    
class AliyunRESTService(object):
    http_server = http.HttpServer(port=7072)
    http_server.logfile_path = log.get_logfile_path()
    
    NO_DAEMON = 'no_deamon'
    PLUGIN_PATH = 'plugin_path'
    WORKSPACE = 'workspace'
    
    def __init__(self, config={}):
        self.config = config
        plugin_path = self._get_config(self.PLUGIN_PATH)
        if not plugin_path:
            plugin_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'plugins')
        self.plugin_path = plugin_path
        self.plugin_rgty = plugin.PluginRegistry(self.plugin_path)
    
    def _get_config(self, name):
        return None if not self.config.has_key(name) else self.config[name]
    
    def start(self, in_thread=True):
        config = {}
        self.plugin_rgty.configure_plugins(config)
        self.plugin_rgty.start_plugins()
        if in_thread:
            self.http_server.start_in_thread()
        else:
            self.http_server.start()
    
    def stop(self):
        self.plugin_rgty.stop_plugins()
        self.http_server.stop()

class AgentResponse(object):
    def __init__(self, success=True, error=None):
        self.success = success
        self.error = error if error else ''

class AgentCommand(object):
    def __init__(self):
        pass

def _build_url_for_test(paths):
    builder = http.UriBuilder('http://localhost:7072')
    for p in paths:
        builder.add_path(p)
    return builder.build()

def replyerror(func):
    @functools.wraps(func)
    def wrap(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            content = traceback.format_exc()
            err = '%s\n%s\nargs:%s' % (str(e), content, pprint.pformat([args, kwargs]))
            rsp = AgentResponse()
            rsp.success = False
            rsp.error = str(e)
            logger.warn(err)
            return jsonobject.dumps(rsp)
        
    return wrap

class AliyunDaemon(daemon.Daemon):
    def __init__(self, pidfile, config={}):
        super(AliyunDaemon, self).__init__(pidfile)
        
    def run(self):
        self.agent = new_rest_service()
        self.agent.start(in_thread=False)

SEND_COMMAND_URL = 'SEND_COMMAND_URL'
HOST_UUID = 'HOST_UUID'