import socket
import pygame
from pygame import Rect as R
from pygame import Color as C
from pygame import Surface as S
from pygame.sprite import Sprite
from pygame.sprite import Group as G
from queue import Queue
from pathlib import Path
from uuid import getnode, uuid4, UUID
from json import load, dump, loads, dumps
from math import floor, ceil
from datetime import datetime
from sys import argv
from time import time
import io

# глобальное значение для увеличения/уменьшения блоков
GLOBAL_SCALE = 2

# байтов под определение длины блока для мультиплеера
PACKEGE_MAX_DATA_LEN = 4

# байтов под определение типа блока
NAME_SPACE_BYTES = 7

# размер буфера для пакета в мультиплеере
BUFFER_SIZE = 1024  # 16384


SYSTEM_COMANDS = {
    'escape': [768, 27, 0],
    'lmb': [1025, 1, 0],
    'rmb': [1025, 3, 0],
    'scroll_up': [1027, (0, 1), 0],
    'scroll_down': [1027, (0, -1), 0],
}

# tools
def toBinary(n):
    return ''.join(str(1 & int(n) >> i) for i in range(64)[::-1])

def calc_animation(fps, duration, every=12):
    frames = int(round((int(floor(fps))*duration) / every))
    return [(1, frames+1), frames+1]
    # я сильно сомневаюсь что это будет работать потом

def to_coord_line(coord_matrix):
    line_matrix = []
    for coord_line in coord_matrix:
        line_matrix.extend(coord_line if isinstance(coord_line, (list, tuple)) else [coord_line])
    return set(line_matrix)
    # преобразование матрицы вида [[a,b,...],[c,d,...],...] в матрицу [a,b,c,d,...]

def _wait_first_event(event):
    ignored_keys = [
        1073742051, 1073742055, 1073742081, 1073741881, 1073741895, 1073742053,
        1073742049, 1073742052, 1073742048, 1073742054, 1073742050, 1073742055,
        1073742051, 1073741907, 27
    ]
    ignored_mods = [8192, 4096, 3072, 768, 192, 3]
    approved_type = [pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL]
    if event.type in approved_type:
        mods = pygame.key.get_mods()
        if any([mods&m == m for m in ignored_mods]):
            return False
        if event.type == pygame.KEYDOWN and event.key not in ignored_keys:
            return [event.type, event.key, mods]
        if event.type == pygame.MOUSEBUTTONDOWN:
            if pygame.event.wait(5).type == 1026:
                mw = pygame.event.wait(5)
                if mw.type == 1027:
                    return [mw.type, (mw.x, mw.y), mods]
            return [event.type, event.button, mods]
    return False

def get_first_event():
    find_event = False
    event_as_simple_object = False
    while not find_event:
        event_as_simple_object = _wait_first_event(pygame.event.wait())
        if event_as_simple_object != False:
            find_event = True
    return event_as_simple_object

class ActionAnswer(object):
    def __init__(self, action_name=None, action=None, mods=None, key=False, result=False):
        self.action_name = action_name
        self.action = action
        self.mods = mods

        self.key = key
        self.result = result

    def __or__(self, other):
        return self.result or other.result

    def __and__(self, other):
        return self.result and other.result

    def __bool__(self):
        return self.result

    def pack(self):
        grid, cell = Grid.define_cell_by_x_and_y(*pygame.mouse.get_pos())
        position = None
        if grid is not None:
            position = f'{grid.uuid}:{grid.player};{cell[0]},{cell[1]}'
        return create_pack('Event', dumps({'name':self.action_name, 'action':self.action, 'mods':self.mods, 'key':self.key, 'pos': position, 'result':self.result}))

def determinate_action(event, actions_conf, action_name):
    mods = pygame.key.get_mods()
    action = actions_conf.get(action_name, None)
    if action is None or mods != action[2]:
        return ActionAnswer(action_name=action_name, action=action, mods=mods, result=False)

    if event.type == action[0]:
        if event.type == pygame.KEYDOWN:
            if event.key == action[1]:
                return ActionAnswer(action_name=action_name, action=action, mods=mods, result=True)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == action[1]:
                return ActionAnswer(action_name=action_name, action=action, mods=mods, result=True)
        if event.type == pygame.MOUSEWHEEL:
            if event.x == action[1][0] and event.y == action[1][1]:
                return ActionAnswer(action_name=action_name, action=action, mods=mods, result=True)
    return ActionAnswer(action_name=action_name, action=action, mods=mods, result=False)

def determinate_key_pressed_action(keys, actions_conf, action_name):
    mods = pygame.key.get_mods()
    action = actions_conf.get(action_name, None)
    if action is None or mods != action[2]:
        return ActionAnswer(action_name=action_name, action=action, mods=mods, key=True, result=False)
    return ActionAnswer(action_name=action_name, action=action, mods=mods, key=True, result=keys[action[1]])

# multiplayer tools
def create_pack(name, data):
    data = data.encode()
    while len(name) < NAME_SPACE_BYTES:
        name += ' '
    return f'{name}'.encode() + int(toBinary(len(data)), 2).to_bytes(PACKEGE_MAX_DATA_LEN, 'big') + data

# multiplayer system tools
# meta data
def create_meta(name, data):
    return f'ClientMetaData[{name}]:{data}'

def determinate_meta(data):
    if data.startswith('ClientMetaData'):
        return True
    return False

def extract_meta(data):
    if data.startswith('ClientMetaData'):
        meta_data_type = data[data.find('[')+1:data.find(']')]
        meta_data = data[data.find(':')+1:]
    return (meta_data_type, meta_data)


# GAME SYSTEMS

class FileSettings(object):
    default = {}

    def __init__(self, dump_file='controll_binding_keys.json'):
        self.dump_file = dump_file
        if not Path(self.dump_file).is_file():
            with open(self.dump_file, 'w') as json_file:
                self.dump_base(json_file)
        else:
            try:
                with open(self.dump_file, 'r') as json_file:
                    self.config = load(json_file)
            except:
                with open(self.dump_file, 'w') as json_file:
                    self.dump_base(json_file)
                with open(self.dump_file, 'r') as json_file:
                    self.config = load(json_file)
    def dump_base(self, file):
        dump(self.__class__.default, file, indent=4)

    def dump_config(self, file):
        dump(self.config, file, indent=4)

    def save(self):
        with open(self.dump_file, 'w') as json_file:
            self.dump_config(json_file)

    def set(self, key, value):
        self.config[key] = value

    def get(self, key):
        return self.config[key]


class RemoveObj(object):
    def __init__(self, _type, addr):
        self.type = _type
        self.addr = addr  #uuid:player

    def pack(self):
        return create_pack(f'R{self.type}', self.addr)


class UserID(FileSettings):
    default = {
        'UUID': str(uuid4())
    }


# Управление игровы состоянием и объектами
class GameState(object):
    default = {}

    s_grids = {}
    s_blocks = {}
    s_blocks_in_space = {}

    # multiplayer
    u_ = {}
    u_p = {}
    remove_queue = Queue(2048)
    accept_queue = Queue(2048)
    state_queue  = Queue(2048)

    user_actions = Queue(4096)

    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super(GameState, cls).__new__(cls)
        return cls.instance

    @classmethod
    def set_default(cls, default={}):
        cls.default = default
        # синглетон
    # хранит в себе все игровые объекты
    # нужен для доступу к обектам. зачем? иногда некоторые части пишуться еще до того как они будут созданы
    # или же используються до того момента как будут объявлены

    # изменение внутреигровой логики
    @classmethod
    def logic_layer(cls):
        pass

    @classmethod
    def draw_layer(cls, display):
        cls.simple_bloks.update(display)

    @classmethod
    def add_user(cls, user):
        cls.u_[user] = {
            's_grids':  [],
            's_blocks': [],
            's_blocks_in_space': []
        }

    @classmethod
    def set_palyer(cls, user, player):
        cls.u_p[user] = player


# Управление курсором
class CursorLoader(object):
    # инициализация модуля управления курсором
    # загрузка изображений курсора + создание прямоугольника для него
    # вычисление модификатора позиции для x и y положения курсора (визуальное соответсвие позиции)
    def __init__(self, cursor_map, curent_cursor, cursor_block=(32, 32)):
        # прячет курсор
        pygame.mouse.set_visible(False)

        # название курсора в карте
        self.curent_cursor = curent_cursor
        # карта курсоров название: путь к файлу
        self.cursor_map = cursor_map
        # карта курсоров название: обїект картинки
        self._cursor_map = {}
        # загрузка курсоров
        for cursor, file_path in self.cursor_map.items():
            self._cursor_map[cursor] = pygame.image.load(file_path)
        # создание прямоугольника курсора
        self._cursor_rect = pygame.Rect((0,0), cursor_block)

        # возможность изменить курсор (влияет на определенные функции изменеия, такие как установ4ка дефолтного курсора)
        # к примеру когда зажата кнопка, курсор блокируеться до ее отжимания
        self._lock = False


    # обновление позиции курсора
    def update(self):
        # получение координат
        curent_x, curent_y = pygame.mouse.get_pos()
        # установка позиции прямоугольника курсора так чтобы курсор был в верхнем левом углу, угол указывает на позицию
        self._cursor_rect.left = curent_x
        self._cursor_rect.top = curent_y


    # размещение курсора на экране
    def blit(self, screen):
        # отрисовка курсора на экране
        screen.blit(*(self._cursor_map[self.curent_cursor], self._cursor_rect))

    # установка заданного курсора
    def set_cursor(self, cursor):
        # устанавливает курсор с именем, если курсор не заблокирован
        if cursor in self._cursor_map.keys():
            if not self._lock:
                self.curent_cursor = cursor

    # математическое управление курсором
    def get_cursor_index(self):
        # получает индекс курсора
        return list(self._cursor_map.keys()).index(self.curent_cursor)

    def get_max_index(self):
        # получает максимальный индекс курсора
        return len(self._cursor_map.keys())-1

    def set_cursor_index(self, index):
        # устанавливает курсор по индексу, если курсор не заблокирован
        if index >= 0 and index <= self.get_max_index():
            if not self._lock:
                self.curent_cursor = list(self._cursor_map.keys())[index]

    # блокировка/разблокировка возможности установки дрогого курсора
    def lock(self):
        self._lock = True

    def unlock(self):
        self._lock = False

    # установка первого курсора в карте
    def set_default_cursor(self):
        self.set_cursor_index(0)

    # алиас к стандартной функции
    @property
    def position(self):
        return pygame.mouse.get_pos()


class Actions(FileSettings):
    
    default = {}

    def change(self, action_name, event_type, bind_key, mods):
        self.set(action_name, [event_type, bind_key, mods])


    def action(self, action_name):
        return self.get(action_name)  #(event.TYPE, event.KEY|event.button)


    def valid(self, event_type, bind_key, mods):
        for action, event in self.config.items():
            if event == [event_type, bind_key, mods]:
                return action
        return True

    # types = [KEYDOWN, KEYUP, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEWHEEL]
    # if KEYDOWN, KEYUP
    #     key,
    # if MOUSEBUTTONDOWN, MOUSEBUTTONUP
    #     bitton,
    # if MOUSEWHEEL
    #     (x, y),

    # IGNORE KEY
    # K_LSUPER              left Windows key
    # K_RSUPER              right Windows key
    # K_MODE                mode shift
    # K_SCROLLOCK           scrollock
    # K_RSHIFT              right shift
    # K_LSHIFT              left shift
    # K_RCTRL               right control
    # K_LCTRL               left control
    # K_RALT                right alt
    # K_LALT                left alt
    # K_RMETA               right meta
    # K_LMETA               left meta
    # K_ESCAPE      ^[      escape

    # buttons
    # lmb = 1
    # cmb = 2
    # rmb = 3
    # mb 4,5,6,7,8,9,...


    # MODS
    # KMOD_NONE     no modifier keys pressed
    # KMOD_LSHIFT   left shift
    # KMOD_RSHIFT   right shift
    # KMOD_LCTRL    left control
    # KMOD_RCTRL    right control
    # KMOD_LALT     left alt
    # KMOD_RALT     right alt
    # ?
    # KMOD_LMETA    left meta
    # KMOD_RMETA    right meta
    # KMOD_MODE     AltGr

    # IGNORE MODS
    # KMOD_SHIFT    left shift or right shift or both
    # KMOD_CTRL     left control or right control or both
    # KMOD_ALT      left alt or right alt or both
    # KMOD_META     left meta or right meta or both
    # KMOD_CAPS     caps lock
    # KMOD_NUM      num lock

    # type, key|button|(x,y), mods
    # a = action_modul.action('move_left'== a)
    # if event.type == a[0] and event.key == a[1] and event.mod & a[2]:...


# событие от игрока
class Event(object):
    # отвечает за указание выполнение этого события на клиенте(True) или на сервере(False)
    local = True
    def __init__(self, condition_handler, handler):
        # функция описывающая условие сробатывания
        self.condition_handler = condition_handler
        # функция описывающая оброботчик
        self.handler = handler

    # пара condition_handler и handler для обычных событий
    @classmethod
    def condition_handler(cls, event) -> ActionAnswer: pass
    @classmethod
    def handler(cls, event): pass

    # пара condition_handler и handler для зажатых кнопок
    @classmethod
    def k_condition_handler(cls, keys) -> ActionAnswer: pass
    @classmethod
    def k_handler(cls, keys): pass


# менеджер для единичного вызова цыкла получения событий
class GlobalLoader(object):
    def __init__(self, *loaders):
        # список всех загрузчиков событий
        self.loaders = loaders

    def add(self, *loaders):
        self.loaders += loaders

    # запускает сначало оброботчик всех обычных событий, потом событий от зажатых клавишь
    def update(self):
        self._update()
        self._k_update()

    def _update(self):
        # получение событий и передача их в оброботчики
        for event in pygame.event.get():
            for loader in self.loaders:
                answer = loader.update(event)
                if answer:
                    break

    def _k_update(self):
        # получение зажатых кнопок и передача их в оброботчики
        keys = pygame.key.get_pressed()
        for loader in self.loaders:
            answer = loader.k_update(keys)
            if answer:
                break


# описует загрузчик
class ABS_Loader(object):
    def __init__(self, *events):
        self.events = events  # список событий
        self.global_modificator = lambda: True  # глобальный модификатор

    # установка нового глобального модиификатора, функции без параметров
    def set_global_modificator(self, handler):
        self.global_modificator = handler
        return self

    # описание оброботчика событий
    def update(self, event): pass

    # описание оброботчика зажатых клавишь
    def k_update(self, keys): pass


# менеджер событий
class EventLoader(ABS_Loader):
    # оброботчика событий
    def update(self, event):
        # проверка глобального модификатора
        if self.global_modificator():
            # для каждого события
            for e in self.events:
                # проверить условие
                ech = e.condition_handler(event)
                if ech:
                    if MultiPlayer._instance is None or MultiPlayer._instance._role == 'server':
                        # выполнить
                        e.handler(event)
                    elif e.local:
                        # выполнить
                        e.handler(event)
                    else:
                        # отправить на сервер
                        if not isinstance(ech, ActionAnswer):
                            print('Warning!', e.condition_handler, 'must return', ActionAnswer, 'object!')
                            # Warning example
                            # Warning! <bound method W_GameLoop.ui.<locals>.SimplePlayerControll.condition_handler of
                            # <class '__main__.W_GameLoop.ui.<locals>.SimplePlayerControll'>> must return <class '__main__.ActionAnswer'> object!
                        else:
                            GameState.user_actions.put(ech.pack())
                    return True


# менеджер событий зажатых клавишь
class KeyPressedEventLoader(ABS_Loader):
    # оброботчика событий
    def k_update(self, keys):
        # проверка глобального модификатора
        if self.global_modificator():
            # для каждого события
            for e in self.events:
                # проверить условие
                ech = e.k_condition_handler(keys)
                if ech:
                    if MultiPlayer._instance is None or MultiPlayer._instance._role == 'server':
                        # выполнить
                        e.k_handler(keys)
                    elif e.local:
                        # выполнить
                        e.k_handler(keys)
                    else:
                        # отправить на сервер
                        if not isinstance(ech, ActionAnswer):
                            print('Warning!', e.condition_handler, 'must return', ActionAnswer, 'object!')
                        else:
                            GameState.user_actions.put(e.k_condition_handler(keys).pack())
                    return True

# PlayerView не зависят от сервера или клиента, для всех эти значения ЛОКАЛЬНЫ

# класс игровой камеры.
# он отображает смещение по осям x и y которое будет учитываться во всех координатах при их отрисовке.
class PlayerView(object):
    # количество умножение размера клетки на 2
    user_view_scale = 1

    # возможность скалирования
    can_change_scale = True
    # максимальное количество умножение размера клетки на 2
    user_max_scale = 7
    # минимальное количество умножение размера клетки на 2
    user_min_scale = 1

    # все блоки зависящие от камеры пользователя
    _dr = []

    # созранения прошлых значения
    _last_values = {
        'user_view_scale': 1
    }

    # установка важных елементов для камеры, зависит от display_info, которую можно вызвать только после инициализации pygame
    @classmethod
    def set(cls, display_info):
        # установка смещения камеры пользователя
        cls.user_view_x = display_info.current_w//4
        cls.user_view_y = display_info.current_h//4

        cls._last_values['user_view_x'] = cls.user_view_x
        cls._last_values['user_view_y'] = cls.user_view_y

    # обновление камеры
    @classmethod
    def update(cls, update_rect=True):
        # нету изменеий в позиции и скалировании камеры
        has_change = {
            'user_view_x': (False, 0),
            'user_view_y': (False, 0),
            'user_view_scale': (False, 0)
        }
        for key, value in cls._last_values.items():
            if getattr(cls, key) != cls._last_values[key]:
                # определение изменеий позиции или скалирования
                has_change[key] = (True, getattr(cls, key) - cls._last_values[key])
                # сохранение текущего значения как старое значение
                cls._last_values[key] = getattr(cls, key)

        # обновление всех блоков
        if update_rect:
            for dynamic_r in cls._dr:
                dynamic_r.update_me(*has_change.values())
        else:
            return has_change


# Динамический квадрат
# Реагирует на изменение камеры игрока автоматически с ее обновлением
class DynamicR(R):

    SCALE = GLOBAL_SCALE

    def __init__(self, left, top, width, height, x_i=None, y_i=None, offset_x=0, offset_y=0, player_view=PlayerView):
        super().__init__(left, top, width, height)

        # класс камеры
        self.player_view = player_view
        
        # добавление этой клетки как клетки зависящегй от камеры
        self.player_view._dr.append(self)

        # координаты клетки в сетке относительно 0 клетки в гриде
        self.x_i = x_i
        self.y_i = y_i

        # смещение блока в сетке относительно 0 грида
        self.offset_x = offset_x
        self.offset_y = offset_y

        # просчет позиции координат, относительно 0 клетки в гриде, без смещения от камеры (оригинальная позиции где камера в 0 позиции)
        self.update_me(auto=True)

    # удаление этого клетки
    # вряд ли это вообще когда-то будет юзаться, хотя хз)
    def delete(self):
        self.player_view._dr.remove(self)

    # обновление клетки
    def update_me(self, x=(False, 0), y=(False, 0), s=(False, 0), auto=False):
        # это 0 позиция клетки, у камеры нету никаких изменений
        if auto:
            self.left += self.player_view.user_view_x
            self.top += self.player_view.user_view_y
            self.width *= self.player_view.user_view_scale
            self.height *= self.player_view.user_view_scale
        else:
            # камера начала меняться


            # смещение позиции камеры
            # есть по x
            if x[0]:
                self.left += x[1]
            # есть по y
            if y[0]:
                self.top += y[1]

            # есть, но изменено скалирование
            if s[0]:
                # увеличено
                if s[1] > 0:
                    # добавляем смещение относительно 0 позиции в гриде
                    self.left += self.width*self.x_i
                    self.top += self.height*self.y_i

                    # добавляем смещение относительно 0 грида
                    self.left += self.offset_x*self.width
                    self.top += self.offset_y*self.height

                    # увеличение размера клетки в SCALE раз
                    self.width *= self.SCALE
                    self.height *= self.SCALE
                # уменьшено
                else:
                    # уменьшение размера клетки в SCALE раз
                    self.width //= self.SCALE
                    self.height //= self.SCALE

                    # уменьшение смещения относительно 0 позиции в гриде
                    self.left -= self.width*self.x_i
                    self.top -= self.height*self.y_i

                    # уменьшение смещения относительно 0 грида
                    self.left -= self.offset_x*self.width
                    self.top -= self.offset_y*self.height


# Игровая сетка
class Grid(object):
    # ширина и высота блоков
    x_size = 0
    y_size = 0

    # список всех гридов
    _grids = []


    # very important thing: x, y may be multiples __SCALE
    # размер сетки считаеться от min до 0 + 0 до max-1 (-100:99 => 200 клеток)
    def __init__(self, x, y, min_x=-4, max_x=5, min_y=-4, max_y=5, offset_x=0, offset_y=0, node=getnode(), uuid=None):
        # ширина и высота клеток
        if uuid is None:
            uuid = str(uuid4())
        self.uuid = uuid
        self.player = node
        self.x_size = x
        self.y_size = y

        # сетка ключ координаты вида (0, 0) значение DynamicR
        self._grid = {}

        # вряд ли еще понадобиться, но пусть будет
        self._intermediate_frames = {}
        # блоки, игровые обекты произвольной формы, рамещенные на клетках грида
        self._blocks = []

        # максимальные и минимальные координаты клеток по x и y
        self.x_range = (min_x, max_x)
        self.y_range = (min_y, max_y)

        # смещение координаты 0 клетки клеток по x и y
        self.offset_x = offset_x
        self.offset_y = offset_y

        # добавление в список гридов
        self.__class__._grids.append(self)
        GameState.s_grids[f'{self.uuid}:{self.player}'] = self

        # DynamicR имеющий только ширину и высоту
        self.r = DynamicR(0, 0, self.x_size, self.y_size, 0, 0, 0, 0)


    def _change_packeges(self):
        return f'{self.uuid};{self.player};{self.x_size};{self.y_size};{self.offset_x};{self.offset_y};{self.x_range[0]},{self.x_range[1]};{self.y_range[0]},{self.y_range[1]}'

    def _accept_pack(self):
        return f'{self.uuid};{self.player}'


    def package_state(self, accept=False):
        if accept:
            data = self._accept_pack()
        else:
            data = self._change_packeges()
        return create_pack('Grid', data)


    # список всех блоков которые имеют физичиское свойство is_block
    def get_blocks(self):
        return [block for block in self._blocks if block.physical_stats['is_block']]

    # удаление грида
    @classmethod
    def remove_grid(cls, grid):
        if grid in cls._grids:
            cls._grids.remove(grid)
            GameState.s_grids.remove(grid)
            GameState.remove_queue.put(RemoveObj('Grid', f'{grid.uuid}:{grid.player}'))

    def remove(self):
        cls._grids.remove(self)
        del GameState.s_grids[f'{self.uuid}:{self.player}']
        GameState.remove_queue.put(RemoveObj('Grid', f'{self.uuid}:{self.player}'))

    # проводит расчеты по координатам сетки, создает ячейки сетки.
    def init_grid(self):
        for x in range(*self.x_range):
            for y in range(*self.y_range):
                self._grid[(x, y)] = DynamicR(
                    x*self.x_size+self.offset_x*self.x_size, y*self.y_size+self.offset_y*self.y_size,
                    self.x_size, self.y_size, x, y, self.offset_x, self.offset_y
                )
                self._intermediate_frames[(x, y)] = {}

    # рисует прямоугольники, но только те что в зоне видимости (TODO)
    def draw(self, screen):
        for cell in self._grid.values():
            pygame.draw.rect(screen, (255,255,255,0), cell, width=1)

    # отрисовать все гриды
    @classmethod
    def draw_all_grids(cls, screen):
        for grid in cls._grids:
            grid.draw(screen)

    # создать и расчитать все гриды
    @classmethod
    def init_all_grids(cls):
        for grid in  cls._grids:
            grid.init_grid()

    # определить грид, и индекс клетки, в координатах x, y (px)
    @classmethod
    def define_cell_by_x_and_y(cls, x, y):
        # выбранный грид и клетка
        selected_grid = None
        selected_cell = None

        # проходимся по гридам
        for grid in cls._grids:

            # макс и мин позиции(в px) для этого грида
            top_left = (grid.x_range[0], grid.y_range[0])
            bottom_right = (grid.x_range[1]-1, grid.y_range[1]-1)

            min_x = grid._grid[top_left].left
            min_y = grid._grid[top_left].top

            max_x = grid._grid[bottom_right].right
            max_y = grid._grid[bottom_right].bottom

            # находиться ли координаты в гриде 
            if (x >= min_x and x <= max_x) and (y >= min_y and y <= max_y):
                # расчет индекса клетки в которой находяться x, y (px)
                x = ceil(x - PlayerView._last_values['user_view_x'] - grid.offset_x*grid.r.width)//grid.r.width
                y = ceil(y - PlayerView._last_values['user_view_y'] - grid.offset_y*grid.r.height)//grid.r.height
                # проверка вхождения этих индексов в этот грид
                if (x >= grid.x_range[0] and x < grid.x_range[1]) and (y >= grid.y_range[0] and y < grid.y_range[1]):
                    selected_grid = grid
                    selected_cell = (x, y)
                    break
        return (selected_grid, selected_cell)

    @classmethod
    def from_pack(cls, pack):
        uuid, player, x_size, y_size, offset_x, offset_y, x_range, y_range = pack['data'].split(';')
        if f'{uuid}:{player}' not in GameState.s_grids.keys():
            d_grid = Grid(int(x_size), int(y_size), *list(map(int, x_range.split(','))), *list(map(int, y_range.split(','))), int(offset_x), int(offset_y), int(player), uuid)
            d_grid.init_grid()
            GameState.accept_queue.put(d_grid.package_state(True))
        else:
            GameState.accept_queue.put(GameState.s_grids[f'{uuid}:{player}'].package_state(True))


# WindowSystem и Window не зависят от сервера или клиента, для всех эти значения ЛОКАЛЬНЫ

# блок графического объекта
class UI_Element(object):
    def __init__(self, name, width, height, offset_x, offset_y, layout=0, state=None):
        self.name = name
        self.width = width
        self.height = height

        self.offset_x = offset_x
        self.offset_y = offset_y

        self.layout = layout
        self.state = state
        if state is None:
            self.state = {}

    def draw(self): pass

    def update(self, display): pass


# Система управления окнами
class WindowSystem(object):
    # список всех окон
    _windows = []


    # при открытии окон, они будут залетать в конец списка.
    # для закрытия окна оно будет удаляться из опенед,
    # соответственно не будут отрисовываться

    _opened = []

    # любое окно открыто
    @classmethod
    def any_open(cls, exclude=None):
        if exclude is None:
            exclude = []
        return any(list(map(lambda w: w.open if w.name not in exclude else False, cls._windows)))

    # получить текущее открытое окно
    @classmethod
    def get_opened(cls):
        return cls._opened[-1]

    # закрыть последнее открытое окно
    @classmethod
    def close_last_window(cls):
        cls._opened.remove(cls._opened[-1])

    @classmethod
    def update(cls, display):
        for window in cls._opened:
            window.update(display)


    # проверяет наличие окна в открытых окнах (тех что отрисовуются)
    @classmethod
    def is_open(cls, name):
        for window in cls._opened:
            if window.name == name:
                return True
        return False

    @classmethod
    def get(cls, name):
        for window in cls._windows:
            if window.name == name:
                return window

    @classmethod
    def on_any_window(cls, x, y, exclude=None):
        answer = False
        if exclude is None:
            exclude = []
        for window in cls._opened:
            if window.name not in exclude:
                answer |= window.on_me(x, y)
        return answer


# Окно
class Window(object):

    def __init__(self, name, width, height, offset_x=0, offset_y=0, always_blocks=True):
        # состояние открыто ли окно
        self.open = False
        self._open = False
        # указывает на отсутствие изменеия состояния open
        # так как оно False, при always_blocks=False значенин open не миняеться
        # то есть даже при открытом окне, игра будет продолжаться (для рагаликов всяких, будет прикольно) 
        self.always_blocks = always_blocks

        # название окна
        self.name = name

        # ширин, высота
        self.width = width
        self.height = height

        # смещенние окна в px(!) относительно правого верхнего угла
        self.offset_x = offset_x
        self.offset_y = offset_y

        self._ui = {'default':{}}

        # создание UI
        self.event_loader = self.ui()

        WindowSystem._windows.append(self)

    @property
    def scroll_y(self):
        return 0

    def add_ui_element(self, ui_element, group='default'):
        if group not in self._ui.keys():
            self._ui[group] = {}
        self._ui[group][ui_element.name] = ui_element

    def get_ui_element(self, ui_element_name, group='default'):
        if group in self._ui.keys():
            if ui_element_name in self._ui[group].keys():
                return self._ui[group][ui_element_name]

    # функция для прописи элементов ui, их код
    def ui(self) -> EventLoader: 
        pass

    # логика отрисовки окна 
    def draw(self): pass

    def draw_ui(self, surface): pass

    # отрисовка окна
    def update(self, display): pass

    # открыто ли окно
    def is_open(self):
        return self.open

    # открыть окно (не отрисовать и обрабатывать логику)
    def show(self):
        if self.always_blocks:
            self.open = True
        WindowSystem._opened.append(self)
        self._open = True

    # закрыть окно
    def close(self):
        if self.always_blocks:
            self.open = False
        WindowSystem._opened.remove(self)
        self._open = False

    def toggle(self):
        if self._open:
            self.close()
        else:
            self.show()

    def on_me(self, x, y):
        return (x >= self.offset_x and x <= self.offset_x+self.width and y >= self.offset_y and y <= self.offset_y+self.height)

    def on_button(self, name, x, y, group='default', offset=None):
        if offset is None:
            offset = (0,0)
        button = self._ui[group][name]
        return (x >= button.offset_x+offset[0] and x <= button.offset_x+offset[0]+button.width and y >= button.offset_y+offset[1]-self.scroll_y and y <= button.offset_y+offset[1]-self.scroll_y+button.height)


class ScrollableWindow(Window):
    y_position = 0
    scroll_step_num = 0
    scroll_step = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.y_position = 0
        self.scroll_step_num = 0
        self.scroll_step = 15

    @property
    def scroll_y(self):
        answer = self.scroll_step_num * self.scroll_step
        self.y_position = answer
        return answer

    def scroll_ui(self):
        class Scroll(Event):
            @classmethod
            def condition_handler(cls, event):
                if self in WindowSystem._opened:
                    return (
                        determinate_action(event, SYSTEM_COMANDS, 'scroll_up')
                        or determinate_action(event, SYSTEM_COMANDS, 'scroll_down')
                    )
                return False

            @classmethod
            def handler(cls, event):
                if self in WindowSystem._opened:
                    if determinate_action(event, SYSTEM_COMANDS, 'scroll_up'):
                        if self.scroll_step_num - 1 >= 0:
                            self.scroll_step_num -= 1
                    if determinate_action(event, SYSTEM_COMANDS, 'scroll_down'):
                        self.scroll_step_num += 1
        return Scroll


# Игровой блок, основа любого игрового объекта
class DBlock(Sprite):

    max_packages = 180  # 60 кадров в секунду -> 3 секунды

    def __init__(self, grid, tl_x, tl_y, block_map=None, physical_stats=None, node=getnode(), uuid=None):
        super().__init__()
        if uuid is None:
            uuid = str(uuid4())
        self.uuid = uuid
        self.player = node

        # грид в котором блок
        self.grid = grid

        # индексы верхнегй левок клетки блока
        self.tl_x = tl_x
        self.tl_y = tl_y

        # физические свойства блока
        self.physical_stats = physical_stats
        if physical_stats is None:
            self.physical_stats = {}

        # кешированая позиция
        self.cahce_relative_coords = {
            'x': tl_x,
            'y': tl_y,
            'relative_coords': None
        }

        # описание карти блока
        if block_map is None:
            self._set_block_map(((1, ), ))
        else:
            self._set_block_map(block_map)

        # некоторые физические свойства
        self.physical_stats['y_length'] = len(self.block_map)
        self.physical_stats['x_length'] = 0
        # симетрический блок (к примеру 3х3)
        self.physical_stats['is_symmetric'] = True
        # прямоугольный блок (к примеру 2х4)
        self.physical_stats['is_rectangle'] = True

        last_len = None
        for line in self.block_map:
            _len = line.count(1)
            if last_len is None:
                last_len = _len
            else:
                if _len != last_len:
                    self.physical_stats['is_rectangle'] = False
            if _len != self.physical_stats['y_length']:
                self.physical_stats['is_symmetric'] = False
            if _len > self.physical_stats['x_length']:
                self.physical_stats['x_length'] = _len

        if 'is_block' not in self.physical_stats.keys():
            self.physical_stats['is_block'] = False

        self._update = False

        self.add_to_grid()
        GameState.s_blocks[f'{self.uuid}:{self.player}'] = self


    def _change_packeges(self):
        return dumps({
            'c': f'{self.uuid};{self.player};{self.grid.uuid};{self.grid.player};{self.tl_x};{self.tl_y}',
            's': self.physical_stats,
            'm': self.block_map,
            't': '',
            'a': 'anim_name:frame:off_x:off_y:e_x:e_y'
        })


    def package_state(self):
        data = self._change_packeges()
        return create_pack('DBlock', data)

    # добавить к гриду
    def add_to_grid(self):
        self.grid._blocks.append(self)
        self._update = True

    # удалить из грида
    def remove_from_grid(self):
        if self in self.grid._blocks:
            self.grid._blocks.remove(self)
            self._update = True

    # создание карты блока, в которой описываються индексы клеток относительно tl_x tl_y клетки
    def _set_block_map(self, block_map):
        self.block_map = block_map

        # указывает смещение координат от tl_x tl_y для каждой клетки
        self.block_relative_coords = []

        y = -1
        for line in self.block_map:
            y += 1
            relative_line = []
            x = -1
            for block in line:
                x += 1
                if block == 1:
                    relative_line.append((x, y))
                else:
                    relative_line.append(None)

            self.block_relative_coords.append(relative_line)

    # рачет точных координат на гриде
    def _relative_coords(self, tl_x, tl_y):
        # показывает координаты блока в tl_x tl_y
        relative_coords = []
        for line in self.block_relative_coords:
            relative_line = []
            for block in line:
                if block is not None:
                    relative_line.append((tl_x+block[0], tl_y+block[1]))
                else:
                    relative_line.append(None)
            relative_coords.append(relative_line)
        return relative_coords

    # указывает текущие координаты с учетом использования смещение координат от tl_x tl_y
    @property
    def relative_coords(self):
        # система расчета координат с кешированием

        # проверить, не изменились ли координаты
        if self.cahce_relative_coords['x'] == self.tl_x and self.cahce_relative_coords['y'] == self.tl_y:
            # есть ли запись
            if self.cahce_relative_coords['relative_coords'] is not None:
                # вернуть
                return self.cahce_relative_coords['relative_coords']

        self.cahce_relative_coords['x'] = self.tl_x
        self.cahce_relative_coords['y'] = self.tl_y

        # расчитать
        relative_coords = self._relative_coords(self.tl_x, self.tl_y)

        # закешировать
        self.cahce_relative_coords['relative_coords'] = relative_coords

        # вернуть
        return relative_coords

    def _validate(self, grid, x, y):
        # проверка на вхождение в поле
        ans = [False, False]
        # входит ли индекс x в допустимые значения грида
        if x is not None:
            if x >= grid.x_range[0] and x <= grid.x_range[1]-1:
                ans[0] = True
        # входит ли индекс y в допустимые значения грида
        if y is not None:
            if y >= grid.y_range[0] and y <= grid.y_range[1]-1:
                ans[1] = True
        return ans


    # сложные проверки
    # можэт ли этот блок переместиться на другой грид в координаты верхнего левого блока tl_x tl_y
    def can_i_move_to_grid(self, grid, tl_x, tl_y):
        return self.can_i_move(tl_x, tl_y, grid)

    # можэт ли этот блок переместиться в координаты верхнего левого блока tl_x tl_y
    def can_i_move(self, tl_x=None, tl_y=None, grid=None):
        # точка, если не указана то ссылка на текущее положение
        if tl_x is None:
            tl_x = self.tl_x
        if tl_y is None:
            tl_y = self.tl_y

        # наши координаты в гриде
        # если не указан то это грид в котором находиться блок
        if grid is None:
            grid = self.grid

        # точные координаты
        relative_coords = self._relative_coords(tl_x, tl_y)

        my_coords = None
        # расчет координат вхождения координат для пямоугольных блоков
        if self.physical_stats['is_symmetric'] or self.physical_stats['is_rectangle']:
            tl_block = relative_coords[0][0]
            br_block = relative_coords[-1][-1]

            # вхождение индексов верхнего левого и нижнего правого блока в сетку
            tl_status = self._validate(grid, *tl_block)
            br_status = self._validate(grid, *br_block)

            if not all([*tl_status, *br_status]):
                return False

        # расчет координат вхождения координат для блоков произвольной формы
        else:
            # все мои координаты
            my_coords = to_coord_line(relative_coords)
            result = True
            # проверка всех моих координат на вхождение в грид
            for coord in my_coords:
                if coord is not None:
                    result &= all(self._validate(grid, *coord))

            if not result:
                return result

        # получение блокеров
        if not self.physical_stats['is_block']:
            blokers = grid.get_blocks()
        else:
            blokers = grid._blocks


        # расчет наличия блокеров в гриде и колизии с ним в будущих координатах
        result = True

        # TODO можно оптимизировать, я это знаю))
        # для всех блокеров в гриде
        for block in blokers:
            # если блокер не я сам
            if block != self:
                # все моо координаты
                my_coords = to_coord_line(relative_coords)
                # все его координаты
                block_coords = to_coord_line(block.relative_coords)
                # совпадения координат
                s = (my_coords&block_coords)
                # удаление пустых блоков
                if None in s:
                    s.remove(None)
                # если есть совпадения в наших координатах
                if len(s) > 0:
                    result = False
                    break
        return result

    # переместить блок в другой грид
    def move_to_grid(self, grid, tl_x, tl_y):
        # удалить из этого грида
        self.remove_from_grid()
        # установить новый
        self.grid = grid
        # переместить
        self.move(tl_x, tl_y)
        # добавить к новому гриду
        self.add_to_grid()
        self._update = True

    # переместить в новую точку
    def move(self, tl_x=None, tl_y=None):
        if tl_x is None:
            tl_x = self.tl_x
        if tl_y is None:
            tl_y = self.tl_y
        self.tl_x = tl_x
        self.tl_y = tl_y
        self._update = True


    def use_animation(self, *args, **kwargs):
        self._update = True

    def change_state(self, name, value):
        self.physical_stats[name] = value
        self._update = True

    # отрисовка блока как простой фигуры
    # OUUUUU MYYYYY ;*)
    # Тебя еще ждет отрисовка комплексных фигур из частей спрайтов, да еще и в динамике)
    # + шмот, еквип и все все все что ток может произойти с персом) 
    # МУКИ АДА еще в переди)
    # наслаждайся этими райскими деньками когда тебе не приходиться валять пиксель арт %)

    # так, зткнись *)
    # есть идея
    # прописуем законы создания анимации, типа как, закон движения левой руки при направлении движения в лево
    # потом создаем блок текстур и вооля, штука пашет)
    # правда это чертовски сложная задача, однако такое не видать малолеткам)
    # вот что подымит подобное на уровень трпл А проэетов)

    # просчет елемента отрисовки
    def simple_draw(self):
        # если прямоугольная форма, то можно создать один Surface и нарисовать объект в нем
        if self.physical_stats['is_symmetric'] or self.physical_stats['is_rectangle']:
            # если нету Surface
            if not hasattr(self, 's') or not PlayerView.can_change_scale:
                cell = self.grid._grid[(self.tl_x, self.tl_y)]
                self.s = S((cell.width * self.physical_stats['x_length'], cell.height * self.physical_stats['y_length']))
                self.s.fill(C(255,255,255))

        else:
            # если нет, но тужно создать по отдельному Surface для каждой клетки объекта
            # если нету Surface's
            if not hasattr(self, 'ss') or not PlayerView.can_change_scale:
                self.ss = {}
                cell = self.grid._grid[(self.tl_x, self.tl_y)]
                for line in self.block_relative_coords:
                    for block in line:
                        self.ss[block] = S((cell.width, cell.height))
                        self.ss[block].fill(C(255,0,0))

    # отрисовка Surface на экране
    def simple_update(self, display):
        self.simple_draw()
        if self.physical_stats['is_symmetric'] or self.physical_stats['is_rectangle']:
            display.blit(self.s, self.grid._grid[(self.tl_x, self.tl_y)])
        else:
            for line in self.relative_coords:
                for block in line:
                    if block is not None:
                        x, y = block
                        display.blit(self.ss[(x-self.tl_x, y-self.tl_y)], self.grid._grid[(x, y)])

    def update(self, display):
        self.simple_update(display)
        self._update = False

    def remove(self):
        self.remove_from_grid()
        for group in self.groups():
            group.remove(self)
        del GameState.s_blocks[f'{self.uuid}:{self.player}']
        GameState.remove_queue.put(RemoveObj('DBlock', f'{self.uuid}:{self.player}'))

    @classmethod
    def from_pack(cls, pack):
        data = loads(pack['data'])
        uuid, player, grid_uuid, grid_player, x, y = data['c'].split(';')
        x, y = int(x), int(y)
        block_map = data['m']
        physical_stats = data['s']
        if f'{grid_uuid}:{grid_player}' in GameState.s_grids.keys() and f'{uuid}:{player}' not in GameState.s_blocks.keys():
            grid = GameState.s_grids[f'{grid_uuid}:{grid_player}']
            block = DBlock(grid, x, y, block_map, physical_stats, int(player), uuid)
            GameState.simple_bloks.add(block)
        elif f'{grid_uuid}:{grid_player}' in GameState.s_grids.keys() and f'{uuid}:{player}' in GameState.s_blocks.keys():
            grid = GameState.s_grids[f'{grid_uuid}:{grid_player}']
            block = GameState.s_blocks[f'{uuid}:{player}']
            block.move_to_grid(grid, x, y)


# animation process
# Set Block on coord with PhantomBlock
# Play Animation. Block on own cell.
# 50% Animation. Block and PhantomBlock swapped (Move Block and set PhantomBlock on own old coord).
# End Animation. Remove PhantomBlock
# Game Logic: 0%->50%  (x, y) 50%->100% (x+1, y+1) (linier)
# Game Logic: 0%->100% (x, y) 100%      (x+1, y+1) (cast)
# Game Logic: 0%->10%  (x, y) 90%->100% (x+1, y+1) (cast, неязвимость в процессе выполнения)


class MultiPlayerSettings(FileSettings):
    default = {
        'host':'127.0.0.1',
        'port': 8000
    }
MPS = MultiPlayerSettings('server.json')


class MultiPlayer(object):

    _instance = None
    SERVER_TIMEOUT = .2
    CLIENT_TIMEOUT = .1
    game_state = GameState

    def __init__(self):
        self.addr = (MPS.get('host'), MPS.get('port'))
        self.bufferSize = BUFFER_SIZE
        self.__class__._instance = self
        self._role = None

    def create_server(self):
        self.clients = []
        self.UDPServerSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.UDPServerSocket.settimeout(self.SERVER_TIMEOUT)
        self.UDPServerSocket.bind(self.addr)
        self._role = 'server'

        self._last_connections = {}
        self._connection_player = {}

    def connect_to_server(self):
        self.UDPClientSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.UDPClientSocket.settimeout(self.CLIENT_TIMEOUT)
        self._role = 'client'

        self.UDPClientSocket.sendto(f'{create_meta("UUID", GameState.U_ID.get("UUID"))}\n{create_meta("Player", getnode())}'.encode(), self.addr)

    def server_in_loop(self):
        try:
            message, address = self.UDPServerSocket.recvfrom(self.bufferSize)
            self._last_connections[address] = time()
            if address not in self.clients and address != self.addr:
                self.clients.append(address)
                user = None
                uuid_meta, player_meta = message.decode('utf-8', errors='ignore').split('\n')
                if determinate_meta(uuid_meta):
                    _, user = extract_meta(uuid_meta)

                if determinate_meta(player_meta):
                    _, player = extract_meta(player_meta)

                self.game_state.add_user(user)
                self.game_state.set_palyer(user, player)
                self._connection_player[address] = (user, player)

                self.UDPServerSocket.sendto(b'', address)
            else:
                if message != b'':
                    self.change_state_from_player(message)
                for client in self.clients:
                    self.UDPServerSocket.sendto(self.create_state_for_player(self._connection_player[client]), client)
        except TimeoutError:
            pass                
        except socket.error as e:
            curent_time = time()
            to_remove = []
            for client in self.clients:
                if curent_time - self._last_connections[client] > 2:
                    to_remove.append(client)
            for user_for_remove in to_remove:
                self.clients.remove(user_for_remove)
        except Exception as e:
            print(e)

    # внесение изменений игроков в состояние сервера
    @classmethod
    def change_state_from_player(cls, changes: bytes):
        u_meta, data = cls._get_packs_from_user(changes)
        for pack in data:
            if u_meta['UUID'] in cls.game_state.u_.keys():
                if pack['type'].startswith('Grid'):
                    cls.game_state.u_[u_meta['UUID']]['s_grids'].append(pack['data'])
                elif pack['type'].startswith('DBlock'):
                    cls.game_state.u_[u_meta['UUID']]['s_blocks'].append(pack['data'])

    # создание изменеий сервера для игроков
    @classmethod
    def create_state_for_player(cls, client) -> bytes:
        package = b''
        for grid in cls.game_state.s_grids.values():
            if f'{grid.uuid};{grid.player}' not in cls.game_state.u_[client[0]]['s_grids']:
                ps = grid.package_state()
                if len(package) + len(ps) <= BUFFER_SIZE:
                    package += ps
        for block in cls.game_state.s_blocks.values():
            ps = block.package_state()
            if block.physical_stats.get('static', None) == True:
                if f'{block.uuid};{block.player}' not in cls.game_state.u_[client[0]]['s_blocks']:
                    if len(package) + len(ps) <= BUFFER_SIZE:
                        package += ps
            else:
                if len(package) + len(ps) <= BUFFER_SIZE:
                    package += ps
        return package

    def client_in_loop(self):
        try:
            self.UDPClientSocket.sendto(self.create_state_for_server(), self.addr)
            message, address = self.UDPClientSocket.recvfrom(self.bufferSize)
            self.applay_chsnges_from_server(message)
        except TimeoutError:
            pass
        except ConnectionResetError:
            pass
            # try_reconect
        except Exception as e:
            print(e)

    # создание снимка моего игрового состояния на локалке
    @classmethod
    def create_state_for_server(cls) -> bytes:
        package = f'{create_meta("UUID", GameState.U_ID.get("UUID"))}\n{create_meta("Player", getnode())}\n'.encode()
        if not cls.game_state.accept_queue.empty():
            while not cls.game_state.accept_queue.empty():
                package += cls.game_state.accept_queue.get()
        if not cls.game_state.user_actions.empty():
            while not cls.game_state.user_actions.empty():
                package += cls.game_state.user_actions.get()
        return package

    # применение состояния с сервера
    @classmethod
    def applay_chsnges_from_server(cls, changes: bytes):
        for pack in cls._read_packs(changes):
            if pack['type'].startswith('Grid'):
                Grid.from_pack(pack)
            elif pack['type'].startswith('DBlock'):
                DBlock.from_pack(pack)

    @classmethod
    def _read_packs(cls, changes):
        raw = io.BytesIO(changes)
        packs = []
        while True:
            type_ = raw.read(NAME_SPACE_BYTES)
            if type_ == b'':
                break
            data = raw.read(int.from_bytes(raw.read(PACKEGE_MAX_DATA_LEN), 'big'))
            packs.append({'type':type_.decode('utf-8'), 'data': data.decode('utf-8')})
        return packs

    @classmethod
    def _get_packs_from_user(cls, changes):
        u_meta = {}
        packs = []

        uuid_meta, player_meta, changes = changes.decode('utf-8', errors='ignore').split('\n')

        if determinate_meta(uuid_meta):
            key, value = extract_meta(uuid_meta)
            u_meta[key] = value

        if determinate_meta(player_meta):
            key, value = extract_meta(player_meta)
            u_meta[key] = value

        changes = changes.encode()
        if changes != b'':
            packs = cls._read_packs(changes)
        return u_meta, packs

    # static grids and blocks
    # Гриды сапми по себе статичны, то есть можно только создать и уничтожить грид
    # Так что когда у пользователя пустой s_grids то мы отправляем ему все гриды, а в ответе ожидаем что он их принял
    # тогда записываем эти гриды в s_grids и больше оих не отправляем.
    # Если грид уничтожен отправляем RemoveObj и продолжаем отправлять RemoveObj до тех пор пока клиент не ответит что удалил

    # с блоками все тоже самое только у блока должен быть physical_stats['static'] = True
    # если physical_stats['static'] отличен от True или его нету то блоки кидаем по кд
    # blocks_in_space не могут быть статичными, но они удаляються в разы чаще, + подчиняються правилам, так что blocks_in_space 
    # отвечающие за проигрыш анимаций мы не кидаем так как кидаем указание о анимации и рачитываем ее на клиенте

# ПРИМЕР ПРОСТОЙ ИМПЛЕМЕНТАЦИИ ДЛЯ ТЕСТОВ


# объект описывающий функцию которая будет выполнена на следующем фрейме
class ActionObject(object):
    def __init__(self, name, handler=lambda *args: True, args=None):
        if args is None:
            args = []
        self.name = name
        self.handler = handler
        self.args = args


# очередь функций для селдующего фрейма
class NextFrameQueues(object):
    _queue = {}
    _last_answer = {}

    @classmethod
    def create_queue(cls, name, size=12, QueueClass=Queue):
        if name not in cls._queue.keys():
            cls._queue[name] = QueueClass(size)

    @classmethod
    def get(cls, name):
        if name in cls._queue.keys():
            return cls._queue[name]

    @classmethod
    def add(cls, name, action_object):
        cls.get(name).put(action_object)

    @classmethod
    def update(cls):
        for name, queue in cls._queue.items():
            if name not in cls._last_answer.keys():
                cls._last_answer[name] = {}
            cls._last_answer[name] = {}
            while not queue.empty():
                action_object = cls._queue[name].get()
                cls._last_answer[name][action_object.name] = action_object.handler(*action_object.args)

# ------ GAME ------

if len(argv) > 1:
    GameState.U_ID = UserID(f'user_id_{argv[1]}.json')
else:
    GameState.U_ID = UserID('user_id.json')

pygame.init()  # инит
display_info = pygame.display.Info()  # разрешение экрана

PlayerView.set(display_info)  # подключение разрешения к PlayerView

# статусы глобальной работы и паузы
GameState.EXIT = True
GameState.RUN_STATUS = True
GameState.PAUSE = False  # глобально для партийной РПГ

NextFrameQueues.create_queue('settings')

# установка разрешения игрового экрана
display = pygame.display.set_mode(
    (display_info.current_w//2, display_info.current_h//2), # pygame.FULLSCREEN
)
GameState.display = display
# тайтл игрового экрана
pygame.display.set_caption("The most richest man in Babylon")
# создание часов
clock = pygame.time.Clock()

def placeholder_game_load():
    # создание кгридов
    grid = Grid(4,4)
    grid2 = Grid(4,4, offset_x=12)
    # просчет всех гридов
    Grid.init_all_grids()

    # создание блока игрока
    db = DBlock(grid, 0,0, physical_stats={'is_block':True})

    # создание групы блоков
    simple_bloks = G()
    # добавление го в группу
    simple_bloks.add(db)
    GameState.simple_bloks = simple_bloks
    # это игрок :)
    GameState._player = db

    GameState.game_load_y = True

def placeholder_game_load_client():
    simple_bloks = G()
    GameState.simple_bloks = simple_bloks
    GameState.game_load_y = True

class UserActions(Actions):
    default = {
        'move_camera_top': [768, 1073741906, 0],
        'move_camera_bottom': [768, 1073741905, 0],
        'move_camera_left': [768, 1073741904, 0],
        'move_camera_right': [768, 1073741903, 0],

        'camera_up_scale': [1027, (0, 1), 0],
        'camera_down_scale': [1027, (0, -1), 0],

        'move_user_top': [768, 119, 0],
        'move_user_bottom': [768, 115, 0],
        'move_user_left': [768, 97, 0],
        'move_user_right': [768, 100, 0],

        'user_tp': [1025, 1, 0],
        'game_pause': [768, 32, 0]
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__class__._instance = self

UA = UserActions()


class XQuitEvent(Event):
    @classmethod
    def condition_handler(cls, event):
        return event.type == pygame.QUIT

    @classmethod
    def handler(cls, event):
        GameState.EXIT = False


class W_Main_Menu(Window):

    def ui(self):

        self.add_ui_element(UI_Element('NewGame', 120, 30, 120, 40, state={'button':True, 'text':('New Game', True, 'White'), 'font': pygame.font.SysFont('Arial', 24)}))

        self.add_ui_element(UI_Element('CreateServer', 120, 30, 120, 80, state={'button':True, 'text':('CreateServer', True, 'White'), 'font': pygame.font.SysFont('Arial', 24)}))
        self.add_ui_element(UI_Element('ConnectToServer', 120, 30, 120, 120, state={'button':True, 'text':('Connect To Server', True, 'White'), 'font': pygame.font.SysFont('Arial', 24)}))

        self.add_ui_element(UI_Element('Settings', 120, 30, 120, 160, state={'button':True, 'text':('Settings', True, 'White'), 'font': pygame.font.SysFont('Arial', 24)}))
        self.add_ui_element(UI_Element('Exit', 120, 30, 120, 200, state={'button':True, 'text':('Exit', True, 'White'), 'font': pygame.font.SysFont('Arial', 24)}))

        class QuitEvent(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'lmb') and self.on_button('Exit', *pygame.mouse.get_pos())

            @classmethod
            def handler(cls, event):
                GameState.EXIT = False

        class SettingsEvent(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'lmb') and self.on_button('Settings', *pygame.mouse.get_pos())

            @classmethod
            def handler(cls, event):
                WindowSystem.get('main_menu').close()
                WindowSystem.get('settings_menu').show()

        class StartGameEvent(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'lmb') and self.on_button('NewGame', *pygame.mouse.get_pos())

            @classmethod
            def handler(cls, event):
                WindowSystem.get('main_menu').close()
                if not hasattr(GameState, 'game_load_y'):
                    placeholder_game_load()
                    GameState.game_load_y = True
                WindowSystem.get('game_loop').show()


        class CreateServer(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'lmb') and self.on_button('CreateServer', *pygame.mouse.get_pos())

            @classmethod
            def handler(cls, event):
                WindowSystem.get('main_menu').close()
                if not hasattr(GameState, 'game_load_y'):
                    placeholder_game_load()
                    server = MultiPlayer()
                    server.create_server()
                    GameState.game_load_y = True
                WindowSystem.get('game_loop').show()

        class ConnectToServer(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'lmb') and self.on_button('ConnectToServer', *pygame.mouse.get_pos())

            @classmethod
            def handler(cls, event):
                WindowSystem.get('main_menu').close()
                if not hasattr(GameState, 'game_load_y'):
                    placeholder_game_load_client()
                    server = MultiPlayer()
                    server.connect_to_server()
                    GameState.game_load_y = True
                WindowSystem.get('game_loop').show()

        return EventLoader(QuitEvent, SettingsEvent, StartGameEvent, CreateServer, ConnectToServer).set_global_modificator(lambda: WindowSystem.is_open('main_menu'))

    def draw_ui(self, surface):
        for el in self._ui['default'].values():
            if el.state.get('button', None) is not None:
                surf = el.state['font'].render(*el.state['text'])
                surface.blit(surf, ((el.offset_x, el.offset_y), (el.width, el.height)))

    def draw(self): pass

    def update(self, display):
        self.draw_ui(display)


class W_Settings_Menu(ScrollableWindow):

    def ui(self):
        i = 1
        for action in UA.config.keys():
            self.add_ui_element(UI_Element(action, 120, 30, 120, i*40, state={'button':True, 'text':[action, True, 'White'], 'font': pygame.font.SysFont('Arial', 24)}))
            self.add_ui_element(UI_Element(f'{action}_text', 120, 30, 380, i*40, state={'action':action, 'text':['', True, 'White'], 'font': pygame.font.SysFont('Arial', 24)}), group='labels')
            i += 1

        self.add_ui_element(UI_Element('back', 120, 30, 120, (i+1)*40 + 80, state={'button':True, 'text':['Back', True, 'White'], 'font': pygame.font.SysFont('Arial', 24)}))
        self.add_ui_element(UI_Element('save', 120, 30, 190, (i+1)*40 + 80, state={'button':True, 'text':['Save', True, 'White'], 'font': pygame.font.SysFont('Arial', 24)}))

        class SettingsEvent(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'lmb') and any([self.on_button(name, *pygame.mouse.get_pos()) for name in self._ui['default'].keys()])

            @classmethod
            def handler(cls, event):
                for name in self._ui['default'].keys():
                    if name not in ['back', 'save'] and self.on_button(name, *pygame.mouse.get_pos()):

                        def handler(name):
                            event = get_first_event()
                            if UA.valid(*event) == True:
                                UA.change(name, *event)
                            self.get_ui_element(name).state['text'][2] = 'White'

                        NextFrameQueues.add('settings', ActionObject('catch_next_event', handler, [name]))
                        self.get_ui_element(name).state['text'][2] = 'Red'

                if self.on_button('back', *pygame.mouse.get_pos()):
                    WindowSystem.get('settings_menu').close()
                    WindowSystem.get('main_menu').show()

                if self.on_button('save', *pygame.mouse.get_pos()):
                    UA.save()

        return EventLoader(SettingsEvent, self.scroll_ui()).set_global_modificator(lambda: WindowSystem.is_open('settings_menu'))

    def draw_ui(self, surface):
        for el in self._ui['default'].values():
            if el.state.get('button', None) is not None:
                surf = el.state['font'].render(*el.state['text'])
                surface.blit(surf, ((el.offset_x, el.offset_y-self.scroll_y), (el.width, el.height)))

        for el in self._ui['labels'].values():
            text = UA.action(el.state['action'])
            surf = el.state['font'].render(f'{text}', *el.state['text'][1:])
            surface.blit(surf, ((el.offset_x, el.offset_y-self.scroll_y), (el.width, el.height)))

    def draw(self): pass

    def update(self, display):
        self.draw_ui(display)


class W_GameLoop(Window):

    def ui(self):
        # Описание событий в игре

        # Выход
        class InGameMenuToggle(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'escape')

            @classmethod
            def handler(cls, event):
                WindowSystem.get('in_game_menu').show()


        # Управление камерой и скалированием
        class PlayerViewChangeEvent(Event):
            @classmethod
            def condition_handler(cls, event):
                return (
                    determinate_action(event, UA.config, 'camera_up_scale')
                    or determinate_action(event, UA.config, 'camera_down_scale')
                )

            @classmethod
            def handler(cls, event):
                if determinate_action(event, UA.config, 'camera_up_scale'):
                    if PlayerView.user_view_scale + 1 <= PlayerView.user_max_scale:
                        PlayerView.user_view_scale += 1
                        PlayerView.can_change_scale = False
                if determinate_action(event, UA.config, 'camera_down_scale'):
                    if PlayerView.user_view_scale - 1 >= PlayerView.user_min_scale:
                        PlayerView.user_view_scale -= 1
                        PlayerView.can_change_scale = False

            @classmethod
            def k_condition_handler(cls, keys):
                return (
                    determinate_key_pressed_action(keys, UA.config, 'move_camera_right')
                    or determinate_key_pressed_action(keys, UA.config, 'move_camera_left')
                    or determinate_key_pressed_action(keys, UA.config, 'move_camera_top')
                    or determinate_key_pressed_action(keys, UA.config, 'move_camera_bottom')
                )

            @classmethod
            def k_handler(cls, keys):
                if determinate_key_pressed_action(keys, UA.config, 'move_camera_right'):
                    PlayerView.user_view_x -= 15
                if determinate_key_pressed_action(keys, UA.config, 'move_camera_left'):
                    PlayerView.user_view_x += 15
                if determinate_key_pressed_action(keys, UA.config, 'move_camera_top'):
                    PlayerView.user_view_y += 15
                if determinate_key_pressed_action(keys, UA.config, 'move_camera_bottom'):
                    PlayerView.user_view_y -= 15


        # остановка игры
        class PauseEvent(Event):
            local = False
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, UA.config, 'game_pause')

            @classmethod
            def handler(cls, event):
                GameState.PAUSE = not GameState.PAUSE


        # простое управление игровым блоком
        class SimplePlayerControll(Event):
            local = False
            @classmethod
            def condition_handler(cls, event):
                return ((
                    determinate_action(event, UA.config, 'move_user_right')
                    or determinate_action(event, UA.config, 'move_user_left')
                    or determinate_action(event, UA.config, 'move_user_top')
                    or determinate_action(event, UA.config, 'move_user_bottom')
                ) or (
                    not WindowSystem.on_any_window(*pygame.mouse.get_pos(), exclude=['game_loop'])
                    and determinate_action(event, UA.config, 'user_tp')
                ))

            @classmethod
            def k_condition_handler(cls, keys):
                return (
                    determinate_key_pressed_action(keys, UA.config, 'move_user_right')
                    or determinate_key_pressed_action(keys, UA.config, 'move_user_left')
                    or determinate_key_pressed_action(keys, UA.config, 'move_user_top')
                    or determinate_key_pressed_action(keys, UA.config, 'move_user_bottom')
                )

            @classmethod
            def k_handler(cls, keys):
                if determinate_key_pressed_action(keys, UA.config, 'move_user_right'):
                    if GameState._player.can_i_move(tl_x = GameState._player.tl_x+1):
                        GameState._player.move(tl_x = GameState._player.tl_x+1)
                if determinate_key_pressed_action(keys, UA.config, 'move_user_left'):
                    if GameState._player.can_i_move(tl_x = GameState._player.tl_x-1):
                        GameState._player.move(tl_x = GameState._player.tl_x-1)
                if determinate_key_pressed_action(keys, UA.config, 'move_user_top'):
                    if GameState._player.can_i_move(tl_y = GameState._player.tl_y-1):
                        GameState._player.move(tl_y = GameState._player.tl_y-1)
                if determinate_key_pressed_action(keys, UA.config, 'move_user_bottom'):
                    if GameState._player.can_i_move(tl_y = GameState._player.tl_y+1):
                        GameState._player.move(tl_y = GameState._player.tl_y+1)

            @classmethod
            def handler(cls, event):
                if determinate_action(event, UA.config, 'move_user_right'):
                    if GameState._player.can_i_move(tl_x = GameState._player.tl_x+1):
                        GameState._player.move(tl_x = GameState._player.tl_x+1)

                if determinate_action(event, UA.config, 'move_user_left'):
                    if GameState._player.can_i_move(tl_x = GameState._player.tl_x-1):
                        GameState._player.move(tl_x = GameState._player.tl_x-1)

                if determinate_action(event, UA.config, 'move_user_top'):
                    if GameState._player.can_i_move(tl_y = GameState._player.tl_y-1):
                        GameState._player.move(tl_y = GameState._player.tl_y-1)

                if determinate_action(event, UA.config, 'move_user_bottom'):
                    if GameState._player.can_i_move(tl_y = GameState._player.tl_y+1):
                        GameState._player.move(tl_y = GameState._player.tl_y+1)

                if determinate_action(event, UA.config, 'user_tp'):
                    cgrid, cell = Grid.define_cell_by_x_and_y(*pygame.mouse.get_pos())
                    if cell is not None and GameState._player.can_i_move_to_grid(cgrid, *cell):
                        GameState._player.move_to_grid(cgrid, *cell)


        # ГЛОБАЛЬНЫЕ МОДИФИКАТОРЫ

        # В состоянии игры (нет окон, не на паузе)
        def in_game_modificator():
            return (GameState.RUN_STATUS and not GameState.PAUSE and not WindowSystem.any_open(exclude=['game_loop']))

        # В окне
        def in_window_modificator():
            return WindowSystem.get('game_loop').is_open()

        # ОБРОБОТЧИКИ
        # Глобальные оброботчики
        EL = EventLoader(PlayerViewChangeEvent, PauseEvent).set_global_modificator(in_window_modificator)
        InGameMenu = EventLoader(InGameMenuToggle).set_global_modificator(lambda: in_window_modificator() and not WindowSystem.get('in_game_menu').is_open())
        # Обработчики в игре
        Game_KPE = KeyPressedEventLoader(SimplePlayerControll).set_global_modificator(lambda: in_window_modificator() and in_game_modificator())
        Game_EL = EventLoader(SimplePlayerControll).set_global_modificator(lambda: in_window_modificator() and in_game_modificator())
        # Обработчики в игре, но не учитывая паузу
        No_Window_KPE = KeyPressedEventLoader(PlayerViewChangeEvent).set_global_modificator(in_window_modificator)

        return (EL, Game_KPE, Game_EL, No_Window_KPE, InGameMenu)

    def draw(self):
        pass
        # create ui elements

    def update(self, display):
        # Почему сначало Connection Layer а потом Logic Layer
        # Вы отправили бота
        # игрок отреагировал, нанес урон

        # Logic Layer, Connection Layer
        # бот сместился, урон не прошел

        # Connection Layer, Logic Layer
        # урон прошел, бот сместился

        # Connection Layer

        if MultiPlayer._instance is not None:
            if MultiPlayer._instance._role == 'server':
                MultiPlayer._instance.server_in_loop()
            elif MultiPlayer._instance._role == 'client':
                MultiPlayer._instance.client_in_loop()

        # LogicLayer
        GameState.logic_layer()

        # GAME STAGE
        PlayerView.update()  # обновить сетку, изменить координаты всех объектов в игре
        Grid.draw_all_grids(display)  # отрисовать сетку

        GameState.draw_layer(display)   # отрисовать блоки
        # END GAME STAGE


class W_In_Game_Menu(Window):

    def ui(self):

        self.add_ui_element(UI_Element('ToMainMenu', 120, 30, 120, 40, state={'button':True, 'text':('To Main Menu', True, 'White'), 'font': pygame.font.SysFont('Arial', 24)}))

        class ToMainMenu(Event):
            @classmethod
            def condition_handler(cls, event):
                if hasattr(self, 's'):
                    return self.on_button('ToMainMenu', *pygame.mouse.get_pos(), offset=(self.offset_x, self.offset_y)) and determinate_action(event, SYSTEM_COMANDS, 'lmb') 
                return False

            @classmethod
            def handler(cls, event):
                WindowSystem.get('in_game_menu').close()
                WindowSystem.get('game_loop').close()
                WindowSystem.get('main_menu').show()

        class InGameMenuToggle(Event):
            @classmethod
            def condition_handler(cls, event):
                return determinate_action(event, SYSTEM_COMANDS, 'escape')

            @classmethod
            def handler(cls, event):
                WindowSystem.get('in_game_menu').close()

        return EventLoader(InGameMenuToggle, ToMainMenu).set_global_modificator(lambda: WindowSystem.get('in_game_menu').is_open())

    def draw_ui(self, surface):
        for el in self._ui['default'].values():
            if el.state.get('button', None) is not None:
                surf = el.state['font'].render(*el.state['text'])
                surface.blit(surf, ((el.offset_x, el.offset_y), (el.width, el.height)))

    def draw(self):
        if not hasattr(self, 's'):
            self.s = S((self.width, self.height))
            self.s.fill((125, 0, 0))
        self.draw_ui(self.s)

    def update(self, display):
        self.draw()
        display.blit(self.s, ((self.offset_x,self.offset_y), (self.width, self.height)))


main_menu = W_Main_Menu('main_menu', *(display_info.current_w, display_info.current_h))
W_MainMenu_EL = main_menu.ui()

settings_menu = W_Settings_Menu('settings_menu', *(display_info.current_w, display_info.current_h))
W_SettingsMenu_EL = settings_menu.ui()

game_loop = W_GameLoop('game_loop', *(display_info.current_w, display_info.current_h))
W_GameLoop_EL = game_loop.ui()

in_game_menu = W_In_Game_Menu('in_game_menu',
    *(display_info.current_w//4, display_info.current_h//4),
    *(display_info.current_w//8, display_info.current_h//8)
)
W_InGameMenu_EL = in_game_menu.ui()

# глобальный обработчик событий
# отлавливает все события, включая зажатые клавиши
GL = GlobalLoader(EventLoader(XQuitEvent), W_MainMenu_EL, W_SettingsMenu_EL, *W_GameLoop_EL, W_InGameMenu_EL)

# загрузка курсора
CL = CursorLoader({
    'cursor': 'assets/cursors/cursor.png',
    'link': 'assets/cursors/link.png'
}, 'cursor')


WindowSystem.get('main_menu').show()

while GameState.EXIT:
    clock.tick(60)  # изменение экрана
    display.fill(C(0,0,0))  # заливка экрана
    PlayerView.can_change_scale = True  # возможность изменить приближение в этом кадре
    CL.set_default_cursor()  # установить курсор
    NextFrameQueues.update()
    GL.update()  # отловить события, запустить их обработку, изменить игровое сотояние(игрок)
    # отрисовка окон, просчет логики внутри окна
    WindowSystem.update(display)
    CL.update()  # обновить курсор
    CL.blit(display)  # отрисовать курсор
    # отрисовать экран
    pygame.display.update()

pygame.quit()  # закончить игру :)


# создание панели управления

# система мультиплеера + многопоточность игры (multiprocessing)

# временное решение (возможно, хз как)) 
# при уменьшении отрисовывать не все пиксели, при увеличении (сверх возможного) отрисовывать вместо одного 2на2 пикселя
# создание блока
    # добавление анимации
    # пример простой игровой логики
    # пример простого игрового взаимодействия
    # запуск анимации

# полное взаимодействие шаров отрисовки (все что закрываеться панелью управления не отрисовуется)

# создание гибридных блоков (анимации, спецэфекты)

# добавление первых звуков
# звуки реакции на окружающую среду или взаимодействие

# по мелачам система аудио, настройки аудио,

# создание сохранить/загрузить системы


# создание артов
# продумывание истории
# создание ассетов, звуков
# предметы, скили, мвого сюжета

# ...мханики, персонажы, игровой баланс, вся прочая дичь
# создание локаций
# создание игрой логики

# релиз, и куча бабла)



# Idea 1
# у каждого моба будет лут в котором он одет (как скайрим)
# однако, при получении урона у мобов может повредиться лут,
# что изменит его текстуру и сделает его хламом, + как бонус он больше не будет работать на мобе
# разрушить лут можно только чареным оружием или магией


# Idea 2
# В зависимости от вкаченых навыков, меняеться анимация простоя с определенными вещами
