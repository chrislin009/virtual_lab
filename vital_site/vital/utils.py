import logging
import xmlrpclib
from models import Audit, Available_Config, User_Network_Configuration, Virtual_Machine, \
    User_VM_Config, Course, VLAB_User
import ConfigParser

logger = logging.getLogger(__name__)
config = ConfigParser.ConfigParser()

# TODO change to common config file in shared location
config.read("/home/rdj259/config.ini")


def audit(request, action):
    logger.debug('In audit')
    if request.user.id is not None:
        audit_record = Audit(done_by=request.user.id, action=action)
    else:
        audit_record = Audit(done_by=0, action=action)
        logger.error('An action is being performed without actual user id.')
    audit_record.save()


class XenClient:

    def __init__(self):
        pass

    def list_student_vms(self, server, user, course_id):
        vms = SneakyXenLoadBalancer().get_server(server).list_vms(user)
        prefix = str(user.id) + '_' + str(course_id)
        return [vm for vm in vms if vm['name'].startswith(prefix)]

    def list_all_vms(self, server, user):
        return SneakyXenLoadBalancer().get_server(server).list_vms(user)

    def list_vm(self, server,  user, course_id, vm_id):
        logger.debug('>>>>>>>>IN LIST VM>>>>>>')
        vm = SneakyXenLoadBalancer().get_server(server).list_vm(user, str(user.id) + '_' + str(course_id) + '_' + str(vm_id))
        vm['xen_server'] = server
        return vm

    def register_student_vms(self, user, course):
        # choosing best server under assumption that VM conf and dsk will be on gluster
        xen = SneakyXenLoadBalancer().get_best_server(user, course.id)
        logger.debug(len(course.virtual_machine_set.all()))
        for vm in course.virtual_machine_set.all():
            flag = True
            cnt = 0
            # hack to handle concurrent requests
            while flag:
                available_config = Available_Config.objects.filter(category='MAC_ADDR').order_by('id').first()
                locked_conf = Available_Config.objects.select_for_update().filter(id=available_config.id)
                cnt += 1
                if locked_conf is not None and len(locked_conf) > 0:
                    val = locked_conf[0].value
                    locked_conf.delete()
                    # TODO change this to accept other private networks
                    # Done just to accept class nets
                    class_net = vm.network_configuration_set.filter(is_course_net=True).first()
                    vif = '\'mac=' + val + ', bridge=' + class_net.name + '\''
                    logger.debug('Registering with vif:'+vif+' for user '+user.email)
                    xen.setup_vm(user, str(user.id) + '_' + str(course.id) + '_' + str(vm.id),
                                 str(course.id) + '_' + str(vm.id), vif)
                    user_net_config = User_Network_Configuration()
                    user_net_config.bridge_name = class_net.name
                    user_net_config.user_id = user.id
                    user_net_config.mac_id = val
                    user_net_config.vm = vm
                    user_net_config.save()
                    logger.debug('Registered user ' + user.email)
                    flag = False
                if cnt >= 100:
                    raise Exception('Server Busy : Registration incomplete')




    def unregister_student_vms(self, user, course):
        # choosing best server under assumption that VM conf and dsk will be on gluster
        xen = SneakyXenLoadBalancer().get_best_server(user, course.id)
        for virtualMachine in course.virtual_machine_set.all():
            xen.cleanup_vm(user, str(user.id) + '_' + str(course.id) + '_' + str(virtualMachine.id))
            net_confs_to_delete = User_Network_Configuration.objects.filter(user_id=user.id, vm=virtualMachine)
            if len(net_confs_to_delete) > 0:
                for conf in net_confs_to_delete:
                    available_conf = Available_Config()
                    available_conf.category = 'MAC_ADDR'
                    available_conf.value = conf.mac_id
                    available_conf.save()
                    conf.delete()


    def start_vm(self, user, course_id, vm_id):
        logger.debug('XenClient - in start_vm')
        xen = SneakyXenLoadBalancer().get_best_server(user, course_id)
        vm = xen.start_vm(user, str(user.id) + '_' + str(course_id) + '_' + str(vm_id))
        vm['xen_server'] = xen.name
        return vm

    def stop_vm(self, server, user, course_id, vm_id):
        xen = SneakyXenLoadBalancer().get_server(server)
        xen.stop_vm(user, str(user.id) + '_' + str(course_id) + '_' + str(vm_id))

    def rebase_vm(self, user, course_id, vm_id):
        xen = SneakyXenLoadBalancer().get_best_server(user, course_id)
        virtual_machine = Virtual_Machine.objects.get(id=vm_id)
        net_confs = User_Network_Configuration.objects.filter(user_id=user.id, vm=virtual_machine)
        vif = ''
        for conf in net_confs:
            vif = vif + '\'mac=' + conf.mac_id + ', bridge=' + conf.bridge_name + '\','
        vif = vif[:len(vif)-1]
        xen.setup_vm(user, str(user.id) + '_' + str(course_id) + '_' + str(vm_id), str(course_id) + '_' + str(vm_id),
                     vif)

    def save_vm(self, server, user, course_id, vm_id):
        xen = SneakyXenLoadBalancer().get_server(server)
        xen.save_vm(user, str(user.id) + '_' + str(course_id) + '_' + str(vm_id))

    def restore_vm(self, server, user, course_id, vm_id):
        xen = SneakyXenLoadBalancer().get_server(server)
        xen.restore_vm(user, str(user.id) + '_' + str(course_id) + '_' + str(vm_id), str(course_id) + '_' + str(vm_id))

    # Probably could be removed once the zombie issue is solved
    def kill_zombie_vm(self, server, user, vm_id):
        xen = SneakyXenLoadBalancer().get_server(server)
        xen.kill_zombie_vm(user, vm_id)


class XenServer:

    def __init__(self, name, url):
        self.name = name
        self.proxy = xmlrpclib.ServerProxy(url)

    def list_vms(self, user):
        return self.proxy.xenapi.list_all_vms(user.email, user.password)

    def list_vm(self, user, vm_name):
        return self.proxy.xenapi.list_vm(user.email, user.password, vm_name)

    def setup_vm(self, user, vm_name, base_name, vif=None):
        self.proxy.xenapi.setup_vm(user.email, user.password, vm_name, base_name, vif)

    def cleanup_vm(self, user, vm_name):
        self.proxy.xenapi.cleanup_vm(user.email, user.password, vm_name)

    def stop_vm(self, user, vm_name):
        self.proxy.xenapi.stop_vm(user.email, user.password, vm_name)

    def start_vm(self, user, vm_name):
        return self.proxy.xenapi.start_vm(user.email, user.password, vm_name)

    def save_vm(self, user, vm_name):
        return self.proxy.xenapi.save_vm(user.email, user.password, vm_name)

    def restore_vm(self, user, vm_name, base_vm):
        return self.proxy.xenapi.restore_vm(user.email, user.password, vm_name, base_vm)

    def kill_zombie_vm(self, user, vm_id):
        return self.proxy.xenapi.kill_zombie_vm(user.email, user.password, vm_id)


class SneakyXenLoadBalancer:

    def get_best_server(self, user, course_id):
        """
        Retrieves best server for user and course
        - checks if user has a VM for the specified course already started
            - if yes returns same server
            - if not, then checks server with best stats
                - if more than 1 servers have same stat then pick the first
        :param user: user object
        :param course_id: id of course
        :return: best XenServer instance
        """
        ''' course = Course.objects.get(id=course_id)
vm_confs = User_VM_Config.objects.filter(user_id=user, vm_id__in=course.virtual_machine_set.all())
if len(vm_confs) > 0:
   name = vm_confs[0].xen_server
   return XenServer(name, config.get("Servers", name))
else:
   server_configs = config.items('Servers')
   servers = []
   best_stat = 0
   best_server = 0
   for key, server_url in server_configs:
       server = XenServer(key, server_url)
logger.debug(servers) '''
        name = 'vlab-dev-xen2'
        self.sneak_in_server_stats()
        return XenServer(name, config.get("Servers", name))

    def get_server(self, name):
        return XenServer(name, config.get("Servers", name))

    def sneak_in_server_stats(self):
        # heart beat - 10 seconds stats collection
        server_configs = config.items('Servers')
        user = VLAB_User.objects.get(first_name='Cron', last_name='User')
        for key, server_url in server_configs:
            vms = XenServer(key, server_url).list_vms(user)
            used_memory = sum(list([int(vm['memory']) for vm in vms if vm['name']]))
            logger.debug(">>>>"+used_memory)
