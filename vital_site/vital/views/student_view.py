from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from ..models import Course, Registered_Course, Virtual_Machine
from ..forms import Course_Registration_Form
from ..utils import audit, XenClient
import logging

logger = logging.getLogger(__name__)


# Create your views here.


@login_required(login_url='/vital/login/')
def registered_courses(request):
    logger.debug("In registered courses")
    #  reg_courses = Registered_Courses.objects.filter(user_id=request.user.id, course__status='ACTIVE')
    reg_courses = Registered_Course.objects.filter(user_id=request.user.id)
    message = ''
    if len(reg_courses) == 0:
        message = 'You have no registered courses'
    return render(request, 'vital/registered_courses.html', {'reg_courses': reg_courses, 'message':message})


@login_required(login_url='/vital/login/')
def course_vms(request, course_id):
    logger.debug("in course vms")
    virtual_machines = Virtual_Machine.objects.filter(course_id=course_id)
    vms = XenClient().list_student_vms(request.user, course_id)
    logger.debug('<><><><><><>'+vms[0]['name'])
    for virtual_machine in virtual_machines:
        _vm = next((vm for vm in vms if vm['name'] == virtual_machine.id))
        if _vm is not None:
            virtual_machine.state = 'R'
        else:
            virtual_machine.state = 'S'
    return render(request, 'vital/course_vms.html', {'virtual_machines': virtual_machines})


@login_required(login_url='/vital/login/')
def unregister_from_course(request, course_id):
    logger.debug("in course unregister")
    user = request.user
    reg_courses = Registered_Course.objects.filter(course_id=course_id, user_id=user.id)
    course_to_remove = reg_courses[0]
    audit(request, course_to_remove, 'User '+str(user.id)+' unregistered from course -'+str(course_id))
    course_to_remove.delete()
    return redirect('/vital/courses/registered/')


def dummy_console(request):
    return render(request, 'vital/dummy.html')


def terminal(request):
    return render(request, 'vital/terminal.html')


@login_required(login_url='/vital/login/')
def register_for_course(request):
    logger.debug("in register for course")
    error_message = ''
    if request.method == 'POST':
        form = Course_Registration_Form(request.POST)
        if form.is_valid():
            logger.debug(form.cleaned_data['course_registration_code']+"<>"+str(request.user.id)+"<>"+
                         str(request.user.is_faculty))
            try:
                course = Course.objects.get(registration_code=form.cleaned_data['course_registration_code'])
                user = request.user
                if len(Registered_Course.objects.filter(course_id=course.id, user_id=user.id)) > 0:
                        error_message = 'You have already registered for this course'
                else:
                    if course.capacity > len(Registered_Course.objects.filter(course_id=course.id)) \
                            and course.status == 'ACTIVE':
                        registered_course = Registered_Course(course_id=course.id, user_id=user.id)
                        registered_course.save()
                        audit(request, registered_course, 'User '+str(user.id)+' registered for new course -'+str(course.id))
                        # PLACE TO DO CREATING VMS FOR USER FOR THE COURSE
                        return redirect('/vital/courses/registered/')
                    else:
                        error_message = 'The course is either inactive or has reached its maximum student capacity.'
            except Course.DoesNotExist:
                error_message = 'Invalid registration code. Check again.'
    else:
        form = Course_Registration_Form()
    return render(request, 'vital/course_register.html', {'form': form, 'error_message': error_message})