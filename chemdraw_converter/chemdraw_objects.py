import io
import yaml
from anytree import NodeMixin
from pathlib import Path
from .chemdraw_types import *


class ChemDrawObject(NodeMixin):
    """
    Abstract Base class for any ChemDraw object as defined by cdx format specification on:
    https://www.cambridgesoft.com/services/documentation/sdk/chemdraw/cdx/

    Objects have properties (or in cdxml attributes) which themselves can be objects
    """

    module_path = Path(__file__).parent
    cdx_objects_path = module_path / 'cdx_objects.yml'
    with open(cdx_objects_path, 'r') as stream:
        CDX_OBJECTS = yaml.safe_load(stream)
    cdx_properties_path = module_path / 'cdx_properties.yml'
    with open(cdx_properties_path, 'r') as stream:
        CDX_PROPERTIES = yaml.safe_load(stream)

    def __init__(self, tag_id, element_name, id, properties=[],  parent=None, children=None):

        self.tag_id = tag_id
        self.element_name = element_name
        self.id = id
        self.properties = properties
        self.parent = parent
        if children:
            self.children = children

    @staticmethod
    def from_bytes(cdx) -> 'ChemDrawObject':
        """
        cdx must be a BytesIO instance at the begining of the ID positon. Eg. the tag_id has been read and the next 4
        bytes are the objects id inside the document.
        :param bytes:
        :return:
        """
        raise NotImplementedError("Should have implemented this")

    @staticmethod
    def _read_properties(cdx:io.BytesIO) -> list:

        props = []
        tag_id = int.from_bytes(cdx.read(2), "little")

        while tag_id in ChemDrawObject.CDX_PROPERTIES:
            prop_name = ChemDrawObject.CDX_PROPERTIES[tag_id]['name']
            length = int.from_bytes(cdx.read(2), "little")
            if length > 0:
                if length == 0xFFFF: #special meaning: property bigger than 65534 bytes
                    length = int.from_bytes(cdx.read(4), "little")

                prop_bytes = cdx.read(length)
                chemdraw_type = ChemDrawObject.CDX_PROPERTIES[tag_id]["type"]
                klass = globals()[chemdraw_type]
                type_obj = klass.from_bytes(prop_bytes)
                prop = ChemDrawProperty(tag_id, prop_name, type_obj, length)
                props.append(prop)
            # read next tag
            tag_id = int.from_bytes(cdx.read(2), "little")
        # move back 2 positions, finished reading attributes
        cdx.seek(cdx.tell() - 2)
        return props

    def get_element(self):
        """
        Build and return the cdxml element for this object
        :return:
        """
        raise NotImplementedError("Should have implemented this")

    def get_bytes(self) -> bytes:
        """
        Generates and returns the bytes of this object for adding to a cdx binary file
        :return:
        """
        raise NotImplementedError("Should have implemented this")


class ChemDrawProperty(object):

    def __init__(self, tag_id: int, name: str, type: CDXType, length: int):

        self.tag_id = tag_id
        self.name = name
        self.type = type
        self.length = length

    def to_bytes(self) -> bytes:
        """
        Gets the bytes value representing this property in a cdx document

        :return: bytes representing this property
        """
        stream = io.BytesIO()
        stream.write(self.tag_id.to_bytes(2, byteorder='little'))
        if self.length <= 65534:
            stream.write(self.length.to_bytes(2, byteorder='little'))
        else:
            stream.write(b'\xFF\xFF')
            stream.write(self.length.to_bytes(4, byteorder='little'))
        stream.write(self.type.to_bytes())
        stream.seek(0)
        return stream.read()

    def add_attribute(self, element: ET.Element):
        """
        Adds this property as attribute to the passed in Element

        :param element: an ElementTree element instance
        """
        if self.name == "LabelStyle":
            element['LabelFont'] = self.type.font_id
            element['LabelSize'] = self.type.font_size_points()
            element['LabelSize'] = self.type.font_type
        elif self.name == "CaptionStyle":
            element['CaptionFont'] = self.type.font_id
            element['CaptionSize'] = self.type.font_size_points()
            element['CaptionSize'] = self.type.font_type
        else:
            element[self.name] = self.type.to_property_value()

    def get_value(self):
        return self.type.to_property_value()

    def __repr__(self):
        return '{}: {}'.format(self.name, self.get_value())


class ChemDrawDocument(ChemDrawObject):

    HEADER = b'VjCD0100\x04\x03\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    # According to spec if a "tag_ids" most significant bit (15th bit, 0-based index) is clear, then it's a property
    # else it's an object. This leaves 15 bits resulting gin a max value for a property tag equal to 32767 due to
    # 2^15-1 (max value bits can represent is 2^n-1)
    MAX_PROPERTY_VALUE = 32767

    def __init__(self, id, properties=[], children=None):

        super().__init__(0x8000, 'CDXML', id, properties=properties, children=children)


    @staticmethod
    def from_bytes(cdx:io.BytesIO) -> 'ChemDrawDocument':
        """

        :param cdx: a BytesIO object
        :return:
        """
        header = cdx.read(22)
        if header != ChemDrawDocument.HEADER:
            raise ValueError('File is not a valid cdx file. Invalid header found.')
        document_tag = cdx.read(2)
        if document_tag != b'\x00\x80':
            raise ValueError('File is not a valid cdx file. Document tag not found.')
        object_id = int.from_bytes(cdx.read(4), "little")
        # Document Properties
        props = ChemDrawObject._read_properties(cdx)

        chemdraw_document = ChemDrawDocument(object_id, props)
        parent_stack = [chemdraw_document]
        tag_id = int.from_bytes(cdx.read(2), "little")

        try:
            while tag_id in ChemDrawObject.CDX_OBJECTS:
                class_name = ChemDrawObject.CDX_OBJECTS[tag_id]
                klass = globals()[class_name]
                obj = klass.from_bytes(cdx, parent_stack[-1])
                # read next tag
                tag_id = int.from_bytes(cdx.read(2), "little")
                if tag_id == 0:
                    # end of current object
                    # read next object tag,
                    tag_id = int.from_bytes(cdx.read(2), "little")
                    # check if also reached end of parent object
                    while tag_id == 0:
                        # while parent object is also at end, remove from stack
                        if len(parent_stack) > 0:
                            parent_stack.pop()
                            tag_id = int.from_bytes(cdx.read(2), "little")
                        else:
                            return chemdraw_document
                else:
                    # no object end found, hence we move deeper inside the object tree
                    parent_stack.append(obj)
        except KeyError as err:
            print(err)

        return chemdraw_document


class Page(ChemDrawObject):

    def __init__(self, id, parent, properties=[], children=None):

        super().__init__(0x8001, 'page', id, properties=properties, parent=parent, children=children)

    @staticmethod
    def from_bytes(cdx:io.BytesIO, parent) -> 'Page':
        """
        cdx BytesIO must be at position after object tag but before reading object id.
        :param cdx: byte stream
        :return:
        """
        object_id = int.from_bytes(cdx.read(4), "little")
        props = ChemDrawObject._read_properties(cdx)
        page = Page(object_id, parent, properties=props)
        return page

class Fragment(ChemDrawObject):

    def __init__(self, id, parent, properties=[], children=None):

        super().__init__(0x8003, 'fragment', id, properties=properties, parent=parent, children=children)

    @staticmethod
    def from_bytes(cdx:io.BytesIO, parent) -> 'Fragment':
        """
        cdx BytesIO must be at position after object tag but before reading object id.
        :param cdx: byte stream
        :return:
        """
        object_id = int.from_bytes(cdx.read(4), "little")
        props = ChemDrawObject._read_properties(cdx)
        frag = Fragment(object_id, parent, properties=props)
        return frag


class Node(ChemDrawObject):

    def __init__(self, id, parent, properties=[], children=None):

        super().__init__(0x8004, 'n', id, properties=properties, parent=parent, children=children)

    @staticmethod
    def from_bytes(cdx:io.BytesIO, parent) -> 'Node':
        """
        cdx BytesIO must be at position after object tag but before reading object id.
        :param cdx: byte stream
        :return:
        """
        object_id = int.from_bytes(cdx.read(4), "little")
        props = ChemDrawObject._read_properties(cdx)
        node = Node(object_id, parent, properties=props)
        return node

class Bond(ChemDrawObject):

    def __init__(self, id, parent, properties=[], children=None):

        super().__init__(0x8005, 'b', id, properties=properties, parent=parent, children=children)

    @staticmethod
    def from_bytes(cdx:io.BytesIO, parent) -> 'Bond':
        """
        cdx BytesIO must be at position after object tag but before reading object id.
        :param cdx: byte stream
        :return:
        """
        object_id = int.from_bytes(cdx.read(4), "little")
        props = ChemDrawObject._read_properties(cdx)
        bond = Bond(object_id, parent, properties=props)
        return bond
