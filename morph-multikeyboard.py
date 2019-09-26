#!/usr/bin/env python

##########################################################################
# MIT License
#
# Copyright (c) 2019 Leo Dawn.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
# to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
##########################################################################

# inspired by example_2_sensel_contacts.py provided by sensel in the sensel-python api

import sys

sys.path.append('../sensel-api/sensel-lib-wrappers/sensel-lib-python')
import sensel
import binascii
import threading
import time


class SenselError(Exception):
    def __init__(self, error_num):
        self.error_num = error_num


def warn_on_error(error_num, explaination=''):
    if error_num != 0:
        print('Error detected during sensel operation {} ({})'.format(explaination, error_num))


class Morph:
    def __init__(self, index=0):
        self.handle = self.open(index)
        self.frame = self.init_frame()
        # self.info is not currently used, but this is how to get it. Let's take a look and see what info we get
        self.info = self.close_on_error(sensel.getSensorInfo(self.handle))

    def close_on_error(self, retval):
        try:
            error_num, val = retval
        except:
            error_num = retval
            val = None
        if error_num != 0:
            print('Error detected. Closing')
            self.close_sensel()
            raise SenselError(error_num)
        return val

    def open(self, index=0):
        handle = None
        (error_num, device_list) = sensel.getDeviceList()
        if error_num != 0:
            raise SenselError(error_num)
        if device_list.num_devices > index:
            (error_num, handle) = sensel.openDeviceByID(device_list.devices[index].idx)
            if error_num != 0:
                raise SenselError(error_num)
        return handle

    def init_frame(self):
        self.close_on_error(sensel.setFrameContent(self.handle, sensel.FRAME_CONTENT_CONTACTS_MASK))
        frame = self.close_on_error(sensel.allocateFrameData(self.handle))
        assert frame
        self.close_on_error(sensel.startScanning(self.handle))
        return frame

    def get_frame(self):
        self.close_on_error(sensel.readSensor(self.handle))
        while self.close_on_error(sensel.getNumAvailableFrames(self.handle)) == 0:
            time.sleep(0.05)
        self.close_on_error(sensel.getFrame(self.handle, self.frame))
        return self.frame

    def close_sensel(self):
        if self.handle is not None:
            warn_on_error(sensel.stopScanning(self.handle), 'stop scanning before close')
            warn_on_error(sensel.freeFrameData(self.handle, self.frame), 'free frame data before close')
            warn_on_error(sensel.close(self.handle), 'close handle {}'.format(self.handle))


def open_all_morphs():
    (error_num, device_list) = sensel.getDeviceList()
    if error_num != 0:
        raise SenselError(error_num)
    result = [
        Morph(i)
        for i in range(device_list.num_devices)
    ]
    return result


# I don't like this kluge much, but leave it for now, 'til I:
# TODO: set up an exit handler to replace threaded wait.
def wait_for_enter():
    global enter_pressed
    input("Press Enter to exit...")
    enter_pressed = True
    return


def print_frame(frame):
    assert frame
    if frame.n_contacts > 0:
        print("\nNum Contacts: ", frame.n_contacts)
        for n in range(frame.n_contacts):
            c = frame.contacts[n]
            print("Contact ID: ", c.id)


if __name__ == "__main__":
    enter_pressed = False
    morphs = open_all_morphs()

    t = threading.Thread(target=wait_for_enter)
    t.start()
    while not enter_pressed:
        for morph in morphs:
            print_frame(morph.get_frame())

    for morph in morphs:
        morph.close_sensel()

