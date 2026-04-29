#-----------------------------------------------------------------------------------------------#
# SharpCap Plate Solve Script for Kyushu University BULL's EYE Observatory Sequencer            #
# Developed by Kiyoaki Okudaira * Kyushu University Pegasus Observatory                         #
#-----------------------------------------------------------------------------------------------#
# coding 2025.07.08: 1st coding (ver 1.0.0)                                                     #
# bugfix 2025.07.29: Unabale to delete cash files bug fixed (ver 1.0.3)                         #
#-----------------------------------------------------------------------------------------------#

import subprocess,os
appPATH = os.path.dirname(os.path.abspath(__file__))
subprocess.call(r'del /q "{0}\tmp\tmp.fits"'.format(appPATH),shell=True)
subprocess.call(r'del /q "{0}\tmp\tmp.fits.CameraSettings.txt"'.format(appPATH),shell=True)
SharpCap.Sequencer.RunSequenceFile(r"{0}\SOLVEONLY.scs".format(appPATH))
SharpCap.SelectedCamera.CaptureSingleFrameTo(r"{0}\tmp\tmp.fits".format(appPATH))