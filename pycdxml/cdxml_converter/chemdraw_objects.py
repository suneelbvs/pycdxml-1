from .chemdraw_types import *
import io
import yaml
from pathlib import Path
from lxml import etree as ET
import logging

from ..utils.cdxml_io import etree_to_cdxml

logger = logging.getLogger('pycdxml.chemdraw_objects')


class ChemDrawDocument(object):

    HEADER = b'VjCD0100\x04\x03\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

    CDXML_DEFAULT_DOC_ID = 0
    # According to spec if a "tag_ids" most significant bit (15th bit, 0-based index) is clear, then it's a property
    # else it's an object. This leaves 15 bits resulting in a max value for a property tag equal to 32767 due to
    # 2^15-1 (max value bits can represent is 2^n-1)
    MAX_PROPERTY_VALUE = 32767

    module_path = Path(__file__).parent

    cdx_objects_path = module_path / 'cdx_objects.yml'
    with open(cdx_objects_path, 'r') as stream:
        CDX_OBJECTS = yaml.safe_load(stream)
    ELEMENT_NAME_TO_OBJECT_TAG = {value["element_name"]: key for key, value in CDX_OBJECTS.items()}

    cdx_properties_path = module_path / 'cdx_properties.yml'
    with open(cdx_properties_path, 'r') as stream:
        CDX_PROPERTIES = yaml.safe_load(stream)
    PROPERTY_NAME_TO_TAG = {value["name"]: key for key, value in CDX_PROPERTIES.items()}

    def __init__(self, cdxml: ET.ElementTree):
        self.cdxml = cdxml
        # Use this sequence to set missing id in xml docs
        self.object_id_sequence = iter(range(5000, 100000))

    @staticmethod
    def from_bytes(cdx: io.BytesIO) -> 'ChemDrawDocument':
        """
        :param cdx: a BytesIO object
        :return:
        """
        header = cdx.read(22)
        if header != ChemDrawDocument.HEADER:
            raise ValueError('File is not a valid cdx file. Invalid header found.')
        document_tag = cdx.read(2)
        legacy_doc = False
        if document_tag != b'\x00\x80':
            # legacy files in registration start like below
            # VjCD0100\x04\x03\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03
            # instead of
            # VjCD0100\x04\x03\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x03
            # No document tag and one additional byte. read and ignore said additional byte
            logger.warning('Document tag not found. File seems to be a legacy cdx file.')
            cdx.read(1)
            legacy_doc = True

        object_id = int.from_bytes(cdx.read(4), "little")
        logger.debug('Reading document with id: {}'.format(object_id))
        root = ET.Element('CDXML')
        cdxml = ET.ElementTree(root)
        if legacy_doc:
            # legacy document has additional 23 bytes with unknown meaning, ignore
            # then first property usually is creation program
            cdx.read(23)
        # Document Attributes
        ChemDrawDocument._read_attributes(cdx, root)

        parent_stack = [root]
        tag_id = int.from_bytes(cdx.read(2), "little")

        while tag_id in ChemDrawDocument.CDX_OBJECTS:
            try:
                el = ChemDrawDocument._element_from_bytes(cdx, tag_id, parent_stack[-1])
                logger.debug('Created element of type {} with id: {}'.format(el.tag, el.attrib["id"]))
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
                            logger.info('Finished reading document.')
                            return ChemDrawDocument(cdxml)
                else:
                    # no object end found, hence we move deeper inside the object tree
                    parent_stack.append(el)
            except KeyError as err:
                logger.error('Missing Object Implementation: {}. Ignoring object.'.format(err))

    @staticmethod
    def _element_from_bytes(cdx: io.BytesIO, tag_id: int, parent: ET.Element):
        """
        cdx must be a BytesIO instance at the beginning of the ID position. Eg. the tag_id has been read and the next 4
        bytes are the objects id inside the document.

        :param cdx: BytesIO stream at position right before object ID
        :param tag_id: objects tag identifier
        :return: a new ChemDrawObject
        """
        object_id = int.from_bytes(cdx.read(4), "little")
        element_name = ChemDrawDocument.CDX_OBJECTS[tag_id]['element_name']
        el = ET.SubElement(parent, element_name)
        el.attrib["id"] = str(object_id)
        ChemDrawDocument._read_attributes(cdx, el)
        return el

    @staticmethod
    def _read_attributes(cdx: io.BytesIO, element: ET.Element):

        tag_id = int.from_bytes(cdx.read(2), "little")

        while tag_id in ChemDrawDocument.CDX_PROPERTIES:
            prop_name = ChemDrawDocument.CDX_PROPERTIES[tag_id]['name']
            length = int.from_bytes(cdx.read(2), "little")
            if length == 0xFFFF:  # special meaning: property bigger than 65534 bytes
                length = int.from_bytes(cdx.read(4), "little")
            prop_bytes = cdx.read(length)
            chemdraw_type = ChemDrawDocument.CDX_PROPERTIES[tag_id]["type"]
            logger.debug('Reading property {} of type {}.'.format(prop_name, chemdraw_type))
            klass = globals()[chemdraw_type]
            if prop_name == 'UTF8Text':
                type_obj = klass.from_bytes(prop_bytes, 'utf8')
            else:
                try:
                    type_obj = klass.from_bytes(prop_bytes)
                except ValueError as err:
                    if prop_name == 'color' and length == 4:
                        # A simple test file had a color property instance of length 4
                        # but it's an uint16 and should only be 2 bytes. first 2 bytes contained correct value
                        type_obj = klass.from_bytes(prop_bytes[:2])
                        length = 2
                        logger.warning("Property color of type UINT16 found with length {} instead of required "
                                       "length 2. Fixed by taking only first 2 bytes into account.".format(length))
                    else:
                        raise err

            if prop_name == 'LabelStyle':
                element.attrib['LabelFont'] = str(type_obj.font_id)
                element.attrib['LabelSize'] = str(type_obj.font_size_points())
                element.attrib['LabelFace'] = str(type_obj.font_type)
            elif prop_name == 'CaptionStyle':
                element.attrib['CaptionFont'] = str(type_obj.font_id)
                element.attrib['CaptionSize'] = str(type_obj.font_size_points())
                element.attrib['CaptionFace'] = str(type_obj.font_type)
            elif prop_name == 'fonttable' or prop_name == 'colortable':
                tbl = type_obj.to_element()
                element.append(tbl)
            elif prop_name == 'Text':
                # adds style tags <s></s> to this t element containing styled text
                type_obj.to_element(element)
                logger.debug("Added {} styles to text object.".format(len(type_obj.styles)))
            elif prop_name == 'UTF8Text':
                # Do nothing. This is a new property no in official spec and represents the
                # value of a text objext in UTF-8 inside a cdx file.
                pass
            else:
                element.attrib[prop_name] = type_obj.to_property_value()

            # read next tag
            tag_id = int.from_bytes(cdx.read(2), "little")
            bit15 = tag_id >> 15 & 1
            # Determine if this is a unknown property. Properties have the most significant bit clear (=0).
            # If property is unknown, log it and read next property until a known one is found.
            # 0 is end of object hence ignore here
            while tag_id != 0 and bit15 == 0 and tag_id not in ChemDrawDocument.CDX_PROPERTIES:
                length = int.from_bytes(cdx.read(2), "little")
                cdx.read(length)
                logger.warning('Found unknown property {} with length {}. Ignoring this property.'
                               .format(tag_id.to_bytes(2, "little"), length))
                # read next tag
                tag_id = int.from_bytes(cdx.read(2), "little")
                bit15 = tag_id >> 15 & 1

        logger.debug('Successfully finished reading attributes.')
        # move back 2 positions, finished reading attributes
        cdx.seek(cdx.tell() - 2)

    @staticmethod
    def from_cdxml(cdxml: str) -> 'ChemDrawDocument':
        cdxml_bytes = io.BytesIO(cdxml.encode('utf-8'))
        return ChemDrawDocument(ET.parse(cdxml_bytes))

    def to_bytes(self) -> bytes:
        """
        Generates a cdx file as bytes in memory
        """

        stream = io.BytesIO()
        # Write document to bytes. needs special handling due to font and color tables.
        stream.write(ChemDrawDocument.HEADER)
        root = self.cdxml.getroot()
        self._element_to_stream(root, stream)
        colortable = root.find("colortable")
        fonttable = root.find("fonttable")
        if colortable is not None:
            type_obj = CDXColorTable.from_element(colortable)
            tag_id = ChemDrawDocument.PROPERTY_NAME_TO_TAG['colortable']
            stream.write(tag_id.to_bytes(2, byteorder='little'))
            self._type_to_stream(type_obj, stream)
        if fonttable is not None:
            type_obj = CDXFontTable.from_element(fonttable)
            tag_id = ChemDrawDocument.PROPERTY_NAME_TO_TAG['fonttable']
            stream.write(tag_id.to_bytes(2, byteorder='little'))
            self._type_to_stream(type_obj, stream)

        for child in root:
            self._traverse_tree(child, stream)

        # end of document and end of file
        stream.write(b'\x00\x00\x00\x00')
        return stream.getvalue()

    def to_cdxml(self) -> str:

        return etree_to_cdxml(self.cdxml)

    def _traverse_tree(self, node: ET.Element, stream: io.BytesIO):
        if node.tag not in ['s', 'font', 'color', 'fonttable', 'colortable']:
            # s elements are always in t elements and hence already handled by parent t element
            # this is needed as there is a mismatch between cdx and cdxml
            # same for fonts and colors and font and colortable
            self._element_to_stream(node, stream)
            for child in node:
                self._traverse_tree(child, stream)
            stream.write(b'\x00\x00')

    def _element_to_stream(self, element: ET.Element, stream: io.BytesIO):
        try:
            tag_id = ChemDrawDocument.ELEMENT_NAME_TO_OBJECT_TAG[element.tag]
            stream.write(tag_id.to_bytes(2, "little"))
            if 'id' in element.attrib:
                stream.write(int(element.attrib['id']).to_bytes(4, "little"))
            else:
                # Object Read from cdxml with no ID assigned, give it a default one
                stream.write(next(self.object_id_sequence).to_bytes(4, "little"))

            has_label_style = False
            has_caption_style = False
            for attrib, value in element.attrib.items():
                if attrib in ["LabelFont", "LabelSize", "LabelFace"]:
                    has_label_style = True
                    continue
                if attrib in ["CaptionFont", "CaptionSize", "CaptionFace"]:
                    has_caption_style = True
                    continue
                if attrib == "id":
                    continue
                ChemDrawDocument._attribute_to_stream(attrib, value, stream)

            if element.tag == 't':
                type_obj = CDXString.from_element(element)
                tag_id = ChemDrawDocument.PROPERTY_NAME_TO_TAG['Text']
                stream.write(tag_id.to_bytes(2, byteorder='little'))
                ChemDrawDocument._type_to_stream(type_obj, stream)

            if has_label_style:
                if "LabelFont" in element.attrib:
                    font_id = int(element.attrib["LabelFont"])
                else:
                    logger.warning("Setting default label font id to 1. This might cause an issue if no font with id 1 "
                                   "exists.")
                    font_id = 1
                if "LabelFace" in element.attrib:
                    font_type = int(element.attrib["LabelFace"])
                else:
                    font_type = 0  # plain
                if "LabelSize" in element.attrib:
                    font_size = int(float(element.attrib["LabelSize"]) * 20)
                else:
                    # assume 12 points as default font size. Factor 20 in conversion to cdx units.
                    font_size = 12 * 20

                # color on labels is ignored according to spec
                type_obj = CDXFontStyle(font_id, font_type, font_size, 0)
                tag_id = ChemDrawDocument.PROPERTY_NAME_TO_TAG['LabelStyle']
                stream.write(tag_id.to_bytes(2, byteorder='little'))
                ChemDrawDocument._type_to_stream(type_obj, stream)

            if has_caption_style:
                if "CaptionFont" in element.attrib:
                    font_id = int(element.attrib["CaptionFont"])
                else:
                    logger.warning(
                        "Setting default caption font id to 1. This might cause an issue if no font with id 1 exists.")
                    font_id = 1
                if "CaptionFace" in element.attrib:
                    font_type = int(element.attrib["CaptionFace"])
                else:
                    font_type = 0  # plain
                if "CaptionSize" in element.attrib:
                    font_size = int(float(element.attrib["CaptionSize"]) * 20)
                else:
                    # assume 12 points as default font size. Factor 20 in conversion to cdx units.
                    font_size = 12 * 20

                # color on labels is ignored according to spec
                type_obj = CDXFontStyle(font_id, font_type, font_size, 0)
                tag_id = ChemDrawDocument.PROPERTY_NAME_TO_TAG['CaptionStyle']
                stream.write(tag_id.to_bytes(2, byteorder='little'))
                ChemDrawDocument._type_to_stream(type_obj, stream)

        except KeyError:
            logger.error('Missing implementation for element: {}. Ignoring element.'.format(element.tag))

    @staticmethod
    def _attribute_to_stream(attrib: str, value: str, stream: io.BytesIO):
        try:
            tag_id = ChemDrawDocument.PROPERTY_NAME_TO_TAG[attrib]
            stream.write(tag_id.to_bytes(2, byteorder='little'))
            chemdraw_type = ChemDrawDocument.CDX_PROPERTIES[tag_id]['type']
            klass = globals()[chemdraw_type]
            type_obj = klass.from_string(value)
            ChemDrawDocument._type_to_stream(type_obj, stream)
            logger.debug("Writing attribute {} with value '{}'.".format(attrib, value))
        except KeyError:
            logger.warning('Found unknown attribute {}. Ignoring this attribute.'.format(attrib))

    @staticmethod
    def _type_to_stream(type_obj: CDXType, stream: io.BytesIO):
        prop_bytes = type_obj.to_bytes()
        length = len(prop_bytes)
        if length <= 65534:
            stream.write(length.to_bytes(2, byteorder='little'))
        else:
            stream.write(b'\xFF\xFF')
            stream.write(length.to_bytes(4, byteorder='little'))
        stream.write(prop_bytes)
