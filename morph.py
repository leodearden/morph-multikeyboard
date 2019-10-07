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

from output import Keyboard

sys.path.append('../sensel-api/sensel-lib-wrappers/sensel-lib-python')
import sensel
import traceback
import logging
import itertools
import threading
import queue
from time import sleep

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class SenselError(Exception):
    def __init__(self, error_num):
        self.error_num = error_num


def log_and_warn_on_error(error_num, explanation=''):
    if error_num != 0:
        logging.error('Error detected during sensel operation {} ({})'.format(explanation, error_num))
    else:
        logger.debug('Success: {}'.format(explanation))


class Morph:
    def __init__(self, index=0, tag=''):
        self.handle = self.open(index)
        self.frame = self.init_frame()
        # self.info is not currently used, but this is how to get it. Let's take a look and see what info we get
        self.info = self.close_on_error(sensel.getSensorInfo(self.handle))
        self.contact_frames = queue.Queue(maxsize=1024)
        # self.reader_thread = threading.Thread(name='morph-reader{}'.format(tag), target=self.get_all_contact_frames)
        # self.reader_thread.start()

    def close_on_error(self, retval):
        try:
            error_num, val = retval
        except:
            error_num = retval
            val = None
        if error_num != 0:
            logging.error('Error detected. Closing')
            self.close()
            raise SenselError(error_num)
        return val

    def open(self, index=0):
        handle = None
        (error_num, device_list) = sensel.getDeviceList()
        if error_num != 0:
            raise SenselError(error_num)
        if device_list.num_devices > index:
            device = device_list.devices[index]
            self.serial_num = bytearray(device.serial_num).decode()
            self.com_port = bytearray(device.com_port).decode()
            logging.debug('Opening sensel device {} (idx: {}, serial_num: {}, com_port: {}'.format(index,
                                                                                                   device.idx,
                                                                                                   self.serial_num,
                                                                                                   self.com_port))
            (error_num, handle) = sensel.openDeviceByID(device.idx)
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
        logger.debug('getting frame into {} on handle {}'.format(self.frame, self.handle))
        self.close_on_error(sensel.getFrame(self.handle, self.frame))
        return self.frame

    def read_frames(self):
        logger.debug('getting frame from Morph {}'.format(self.serial_num))
        logger.debug('reading frames from sensor.')
        self.close_on_error(sensel.readSensor(self.handle))
        logger.debug('checking available frames...')
        available_frames = self.close_on_error(sensel.getNumAvailableFrames(self.handle))
        logger.debug('{} frames available'.format(available_frames))
        return (self.get_frame() for _ in range(available_frames))

    def get_contact_frames(self):
        frames = self.read_frames()
        # this would be easier to write and read as nested comprehensions, but harder to debug
        for frame in frames:
            lost = frame.lost_frame_count
            if lost:
                logger.info('{} lost frames since previous frame'.format(lost))
            contact_frame = {}
            for i, contact in enumerate(itertools.islice(frame.contacts, frame.n_contacts)):
                logger.debug('processing contact {} (id {}, state {}, x_pos {}, y_pos {}'.format(i,
                                                                                                 contact.id,
                                                                                                 contact.state,
                                                                                                 contact.x_pos,
                                                                                                 contact.y_pos))
                if contact.state != sensel.CONTACT_INVALID:
                    contact_frame[contact.id] = {
                        'state': contact.state,
                        'x_pos': contact.x_pos,
                        'y_pos': contact.y_pos,
                    }
            if contact_frame:
                self.contact_frames.put(contact_frame)

    def get_all_contact_frames(self):
        while True:
            self.get_contact_frames()

    def close (self):
        if self.handle is not None:

            log_and_warn_on_error(sensel.stopScanning(self.handle),
                                  'stop scanning before close for {}'.format(self.serial_num))
            log_and_warn_on_error(sensel.freeFrameData(self.handle, self.frame),
                                  'free frame data before close for {}'.format(self.serial_num))
            log_and_warn_on_error(sensel.close(self.handle),
                                  'close handle for {} ({})'.format(self.serial_num, self.handle))
            self.handle = None
        else:
            logger.debug('Attempt to close Morph {} with None handle (already closed?)'.format(self.serial_num))


def open_all_morphs():
    (error_num, device_list) = sensel.getDeviceList()
    if error_num != 0:
        raise SenselError(error_num)
    result = [
        Morph(i, tag='-{}'.format(i))
        for i in range(device_list.num_devices)
    ]
    return result


def forever_read_all_morphs(morphs):
    try:
        while True:
            for morph in morphs:
                morph.get_contact_frames()
    except BaseException as e:
        logging.error('caught {} at {}. Exiting.'.format(e, traceback.print_tb(e.__traceback__)))
        for morph in morphs:
            morph.close()



def print_frame(frame):
    assert frame
    if frame.n_contacts > 0:
        print("\nNum Contacts: ", frame.n_contacts)
        for n in range(frame.n_contacts):
            c = frame.contacts[n]
            print("Contact ID: ", c.id)


if __name__ == "__main__":
    morphs = open_all_morphs()
    assert morphs
    assert len(morphs) == 2
    keyboards = [
        Keyboard(morph, layout_file)
        for morph, layout_file in zip(morphs, ['morph-dvorak-left.svg', 'morph-dvorak-right.svg'])
    ]
    forever_read_all_morphs(morphs)
