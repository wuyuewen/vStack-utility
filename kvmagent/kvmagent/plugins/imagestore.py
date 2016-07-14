import os.path
import traceback

from os import symlink, link, unlink, makedirs
from kvmagent import kvmagent
from zstacklib.utils import jsonobject
from zstacklib.utils import http
from zstacklib.utils import linux
from zstacklib.utils import log
from zstacklib.utils import shell

logger = log.get_logger(__name__)

class AgentResponse(object):
    def __init__(self):
        self.totalCapacity = None
        self.availableCapacity = None
        self.success = None
        self.error = None

class ImageStorePlugin(kvmagent.KvmAgent):

    ZSTORE_PROTOSTR = "zstore://"
    ZSTORE_CLI_PATH = "/usr/local/zstack/imagestore/bin/zstcli -rootca /var/lib/zstack/imagestorebackupstorage/certs/ca.pem"
    ZSTORE_DEF_PORT = 8000

    UPLOAD_BIT_PATH = "/imagestore/upload"
    DOWNLOAD_BIT_PATH = "/imagestore/download"
    COMMIT_BIT_PATH = "/imagestore/commit"
    CLIENT_INIT_PATH ="/imagestore/init"

    def start(self):
        http_server = kvmagent.get_http_server()
        http_server.register_async_uri(self.DOWNLOAD_BIT_PATH, self.download_from_imagestore)
        http_server.register_async_uri(self.UPLOAD_BIT_PATH, self.upload_to_imagestore)
        http_server.register_async_uri(self.COMMIT_BIT_PATH, self.commit_to_imagestore)
        http_server.register_async_uri(self.CLIENT_INIT_PATH, self.init_client)

        self.path = None

    def stop(self):
        pass

    def _get_disk_capacity(self):
        return linux.get_disk_capacity_by_df(self.path)

    def _get_image_json_file(self, primaryInstallPath):
        idx = primaryInstallPath.rfind('.')
        if idx == -1:
            return primaryInstallPath + ".json"
        return primaryInstallPath[:idx] + ".json"

    def _get_image_reference(self, primaryStorageInstallPath):
        try:
            with open(self._get_image_json_file(primaryStorageInstallPath)) as f:
                imf = jsonobject.loads(f.read())
                return imf.name, imf.id
        except:
            raise kvmagent.KvmError('unexpected primary storage install path %s' % primaryStorageInstallPath)

    def _parse_image_reference(self, backupStorageInstallPath):
        if not backupStorageInstallPath.startswith(self.ZSTORE_PROTOSTR):
            raise kvmagent.KvmError('unexpected backup storage install path %s' % backupStorageInstallPath)

        xs = backupStorageInstallPath[len(self.ZSTORE_PROTOSTR):].split('/')
        if len(xs) != 2:
            raise kvmagent.KvmError('unexpected backup storage install path %s' % backupStorageInstallPath)

        return xs[0], xs[1]

    def _build_install_path(self, name, imgid):
        return "{0}{1}/{2}".format(self.ZSTORE_PROTOSTR, name, imgid)

    @kvmagent.replyerror
    def init_client(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        self.path = cmd.path

        if not os.path.exists(self.path):
            os.makedirs(self.path, 0755)

        rsp = AgentResponse()
        rsp.totalCapacity, rsp.availableCapacity = self._get_disk_capacity()
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def upload_to_imagestore(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = AgentResponse()

        host = cmd.hostname
        name, imageid = self._get_image_reference(cmd.primaryStorageInstallPath)
        cmdstr = '%s -url %s:%s push %s:%s' % (self.ZSTORE_CLI_PATH, host, self.ZSTORE_DEF_PORT, name, imageid)
        logger.debug('pushing %s:%s to image store' % (name, imageid))
        shell.call(cmdstr)
        logger.debug('%s:%s pushed to image store' % (name, imageid))

        rsp.backupStorageInstallPath = self._build_install_path(name, imageid)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def commit_to_imagestore(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = AgentResponse()

        # Add the image to registry
        fpath = cmd.primaryStorageInstallPath
        cmdstr = '%s -json add -file %s' % (self.ZSTORE_CLI_PATH, fpath)

        logger.debug('adding %s to local image store' % fpath)
        shell.call(cmdstr)
        logger.debug('%s added to local image store' % fpath)

        name, imageid = self._get_image_reference(fpath)
        rsp.backupStorageInstallPath = self._build_install_path(name, imageid)
        rsp.size, rsp.actualSize = linux.qcow2_size_and_actual_size(fpath)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def download_from_imagestore(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = AgentResponse()

        host = cmd.hostname
        name, imageid = self._parse_image_reference(cmd.backupStorageInstallPath)

        cmdstr = '%s -url %s:%s pull -installpath %s %s:%s' % (self.ZSTORE_CLI_PATH, host, self.ZSTORE_DEF_PORT, cmd.primaryStorageInstallPath, name, imageid)
        logger.debug('pulling %s:%s from image store' % (name, imageid))
        shell.call(cmdstr)
        logger.debug('%s:%s pulled to local cache' % (name, imageid))

        rsp.totalCapacity, rsp.availableCapacity = self._get_disk_capacity()
        return jsonobject.dumps(rsp)