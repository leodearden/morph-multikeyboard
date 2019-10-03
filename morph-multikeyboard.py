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
import time
import traceback
import xml.etree.ElementTree as ET
import logging
import itertools
import shapely.geometry
import pyautogui

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

pyautogui.PAUSE = 0.05

class SenselError(Exception):
    def __init__(self, error_num):
        self.error_num = error_num


def log_and_warn_on_error(error_num, explanation=''):
    if error_num != 0:
        logging.error('Error detected during sensel operation {} ({})'.format(explanation, error_num))
    else:
        logger.debug('Success: {}'.format(explanation))


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
        contact_frames = []
        # this would be easier to write and read as nested comprehensions, but harder to debug
        for frame in frames:
            contact_frame = {}
            for contact in frame.contacts:
                contact_frame[contact.id] = {
                    'state': contact.state,
                    'x_pos': contact.x_pos,
                    'y_pos': contact.y_pos,
                }
            contact_frames.append(contact_frame)
        return contact_frames

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
        Morph(i)
        for i in range(device_list.num_devices)
    ]
    return result


def print_frame(frame):
    assert frame
    if frame.n_contacts > 0:
        print("\nNum Contacts: ", frame.n_contacts)
        for n in range(frame.n_contacts):
            c = frame.contacts[n]
            print("Contact ID: ", c.id)


def gen_gen_simple_key_handler(key_code):
    def gen_simple_key_hander(polygon: shapely.geometry.Polygon):
        def key_up():
            pyautogui.keyUp(key_code)

        def handler(p: shapely.geometry.Point):
            if polygon.contains(p):
                pyautogui.keyDown(key_code)
                return key_up
            else:
                return None

        return handler

    return gen_simple_key_hander


def gen_gen_modal_key_handler(key_code, on_mode_change):
    def gen_modal_key_handler(polygon: shapely.geometry.Polygon):
        simple_handler = gen_gen_simple_key_handler(key_code)(polygon)
        def modal_key_up(simple_key_up):
            on_mode_change(False)
            simple_key_up()

        def modal_handler(p: shapely.geometry.Point):
            simple_key_up = simple_handler(p)
            if simple_key_up:
                on_mode_change(True)
                return modal_key_up(simple_key_up)
            else:
                return None

        return modal_handler

    return gen_modal_key_handler


def parse_key_node(key_node):
    # pull out rectangle coords
    rect_node = key_node.findall('rect')
    min_x = rect_node.attrib['x']
    min_y = rect_node.attrib['y']
    max_x = min_x + rect_node.attrib['rx']
    max_y = min_y + rect_node.attrib['ry']
    rect = shapely.geometry.box(min_x, min_y, max_x, max_y)
    # pull out label
    label = ' '.join([chars.lstrip().rstrip() for chars in key_node.itertext()])
    return rect, label


def parse_layout(file_name, keymaps):
    layout_tree = ET.parse(file_name)
    # find all groups that have a rect immediate child and text or flowRoot immediate child
    flowRoot_labelled_key_nodes = layout_tree.getroot().findall('g/rect/../flowRoot/..')
    text_labelled_key_nodes = layout_tree.getroot().findall('g/rect/../text/..')
    # TODO: also parse key nodes that have path outlines (instead of rects)
    layouts = {}
    # TODO: index layout according to x and y to optimise testing contact points.
    for mode, keymap in keymaps.items():
        layout = {}
        for key_node in itertools.chain(flowRoot_labelled_key_nodes, text_labelled_key_nodes):
            rect, label = parse_key_node(key_node)
            handler = keymap[label](rect)
            layout[label] = handler
        layouts[mode] = layout
    return layouts


class Keyboard():
    def __init__(self, morph, layout_file):
        self.morph = morph
        self.keymaps = self.generate_keymaps()
        self.layouts = parse_layout(layout_file, self.keymaps)
        self.layout = self.layouts['base']

    def generate_keymaps(self):
        keymap = {}
        def on_shift_key_change(shift_pressed: bool):
            if shift_pressed:
                self.layout = self.layouts['shifted']
            else:
                self.layout = self.layouts['base']
        keymap['Shift'] = gen_gen_modal_key_handler('shift', on_shift_key_change)
        trivial_keys = [c.upper() for c in 'abcdefghijklmnopqrstuvwxyz']
        trivial_keys.extend(['F{}'.format(n) for n in range(1, 24)])
        trivial_keys.extend(
            ['Esc', 'Tab', 'Caps Lock', 'Alt', 'Ctrl', 'Insert', 'Home', 'End', 'Page Up', 'Page Down', 'Print Screen',
             'Pause Break', 'Back Space', 'Delete', 'Space', 'Enter', ])
        for label in trivial_keys:
            keymap[label] = gen_gen_simple_key_handler(label.lower().replace(' ', ''))
        simple_keys = [
            (u'\u2190', 'left'),
            (u'\u2191', 'up'),
            (u'\u2192', 'right'),
            (u'\u2193', 'down'),
        ]
        for label, name in simple_keys:
            keymap[label] = gen_gen_simple_key_handler(name)
        shiftable_keys = ['! 1', '@ 2', '# 3', '$ 4', '% 5', '^ 6', '& 7', '* 8', '( 9', ') 0', '{ [', '} ]', '? /',
                          '+ =',
                          '_ -', '| \\', ]
        for label in shiftable_keys:
            keymap[label] = gen_gen_simple_key_handler(label[-1])
        base_keymap = dict(keymap)
        for label in shiftable_keys:
            keymap[label] = gen_gen_simple_key_handler(label[0])
        shifted_keymap = dict(keymap)
        return {
            'base': base_keymap,
            'shifted': shifted_keymap,
        }

    def process_contacts(self):
        contacts = self.morph.get_contact_frames()
        for id, contact in contacts.items():
            for key in self.layout.items():
                key(shapely.geometry.Point(contact.x_pos, contact.y_pos))


if __name__ == "__main__":
    morphs = open_all_morphs()
    assert morphs
    assert len(morphs) == 2
    keyboards = [
        Keyboard(morph, layout_file)
        for morph, layout_file in zip(morphs, ['morph-dvorak-left.svg', 'morph-dvorak-right.svg'])
    ]

    try:
        while True:
            # for morph in morphs:
            #     print_frame(morph.get_frame())
            for keyboard in keyboards:
                keyboard.process_contacts()
    except BaseException as e:
        logging.error('caught {} at {}. Exiting.'.format(e, traceback.print_tb(e.__traceback__)))
        for morph in morphs:
            morph.close()
