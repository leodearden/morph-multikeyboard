import shapely.geometry
import itertools
import pyautogui
import xml.etree.ElementTree as ET
import logging
import sys
sys.path.append('../sensel-api/sensel-lib-wrappers/sensel-lib-python')
import sensel
import threading

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

pyautogui.PAUSE = 0

def gen_gen_simple_key_handler(key_code):
    def gen_simple_key_hander(polygon: shapely.geometry.Polygon):

        def key_up():
            logger.debug('sending keyUp({})'.format(key_code))
            pyautogui.keyUp(key_code)

        def handler(p: shapely.geometry.Point):
            if polygon.contains(p):
                logger.debug('sending keyDown({})'.format(key_code))
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
    def __init__(self, morph, layout_file, tag=''):
        self.morph = morph
        self.keymaps = self.generate_keymaps()
        self.layouts = parse_layout(layout_file, self.keymaps)
        self.layout = self.layouts['base']
        self.contact_end_handlers = {}
        self.interpreter_thread = threading.Thread(name='keyboard-interpreter{}'.format(tag),
                                                   target=self.process_all_contacts)
        self.interpreter_thread.start()

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
        contact_frames = self.morph.contact_frames.get()
        for contacts in contact_frames:
            for id, contact in contacts.items():
                if contact['state'] == sensel.CONTACT_START or contact['state'] == sensel.CONTACT_END:
                    contact_point = shapely.geometry.Point(contact['x_pos'], contact['y_pos'])
                if contact['state'] == sensel.CONTACT_START:
                    logger.debug('New contact detected. Calling handlers.')
                    for contact_handler in self.layout.items():
                        result = contact_handler(contact_point)
                        if result:
                            if self.contact_end_handlers[id]:
                                logger.info('Untriggered end handler for contact ID'
                                            ' {}. Missed key up? Triggering.'.format(id))
                                self.contact_end_handlers[id]()
                            self.contact_end_handlers[id] = result
                            break
                elif contact['state'] == sensel.CONTACT_END:
                    logger.debug('Contact end received for ID {}. Calling end handler.'.format(id))
                    self.contact_end_handlers[id]()
                    del self.contact_end_handlers[id]
                # else ignore the contact (for now) - it is either invalid or has simply moved (a drag)
        self.morph.contact_frames.task_done()

    def process_all_contacts(self):
        while True:
            self.process_contacts()
