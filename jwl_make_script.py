import sys
from os.path import dirname, join, exists, basename, splitext, isdir, abspath
from os import mkdir, listdir
from ConfigParser import ConfigParser, NoSectionError

# Load system-specific information
basedir = abspath(dirname(__file__))
config = ConfigParser()
config.read(join(basedir, 'config.ini'))
clean_path = list(sys.path)
path = config.get('basic', 'path').split(';')
sys.path.extend(path) #allows executing any python files in the path
import jwl_make
jwl_make.path = path
jwl_make.clean_path = clean_path

def loadAction(name):
    try:
        module = config.get(name, 'module')
    except NoSectionError:
        raise Exception("could not find action " + name)
    script = __import__(module, globals(), locals(), ['do_action'])
    return script.do_action

if __name__ == '__main__':
    #get action from command line
    args = sys.argv
    if len(args) < 3:
        print "usage: jwl_make project action"
        #print "your args: " + repr(args)
        quit()
    project = args[1]
    action = args[2]
    actionargs = args[3:]
    
    #execute action
    deploypath = join(basedir, 'deploy', project, action)
    do_action = loadAction(action)
    do_action(project, actionargs, deploypath, config)
