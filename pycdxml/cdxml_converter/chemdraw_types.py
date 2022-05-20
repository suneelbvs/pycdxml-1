import io
import yaml
from lxml import etree as ET
from pathlib import Path
from enum import Enum
import logging

logger = logging.getLogger('pycdxml.chemdraw_types')


class CDXType(object):

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXType':
        raise NotImplementedError("Should have implemented this")

    def to_bytes(self) -> bytes:
        raise NotImplementedError("Should have implemented this")

    def to_property_value(self) -> str:
        raise NotImplementedError("Should have implemented this")


class CDXString(CDXType):
    # TODO: implement different charsets from fonttable
    BYTES_PER_STYLE = 10

    def __init__(self, value: str, style_starts=None, styles=None, charset='iso-8859-1'):
        if styles is None:
            styles = []
        if style_starts is None:
            style_starts = []
        self.str_value = value
        self.style_starts = style_starts
        self.styles = styles
        self.charset = charset

    @staticmethod
    def from_bytes(property_bytes: bytes, charset='iso-8859-1') -> 'CDXString':

        stream = io.BytesIO(property_bytes)
        style_runs = int.from_bytes(stream.read(2), "little")
        font_styles = []
        style_starts = []        
        for idx in range(style_runs):
            style_start = int.from_bytes(stream.read(2), "little")
            style_starts.append(style_start)
            font_style = CDXFontStyle.from_bytes(stream.read(8))
            font_styles.append(font_style)
        text_length = len(property_bytes) - (CDXString.BYTES_PER_STYLE * style_runs) - 2
        value = stream.read(text_length).decode(charset)        
        logger.debug("Read String '{}' with  {} different styles.".format(value, len(font_styles)))
        return CDXString(value, style_starts, font_styles, charset)

    @staticmethod
    def from_string(value: str) -> 'CDXString':
        return CDXString(value)

    @staticmethod
    def from_element(t: ET.Element, charset='iso-8859-1') -> 'CDXString':
        """
        create CDXString from a parent xml <t> element
        :return:
        """

        style_starts = []
        font_styles = []
        value = ""
        style_start = 0
        for s in t.iter(tag='s'):
            style_starts.append(style_start)
            value += s.text
            style_start = len(value)
            font_style = CDXFontStyle.from_element(s)
            font_styles.append(font_style)

        logger.debug("Read String '{}' with  {} different styles.".format(value, len(font_styles)))
        return CDXString(value, style_starts, font_styles, charset)

    def to_bytes(self) -> bytes:
        stream = io.BytesIO()
        # number of styles (s elements)
        stream.write(len(self.styles).to_bytes(2, byteorder='little'))
        for idx, style in enumerate(self.styles):
            stream.write(self.style_starts[idx].to_bytes(2, byteorder='little'))
            stream.write(style.to_bytes())
        try:
            stream.write(self.str_value.encode(self.charset))
        except UnicodeError as e:
            logger.error("Caught UnicodeError {}. Retrying with UTF-8".format(e))
            stream.write(self.str_value.encode('utf8'))
        logger.debug('Wrote CDXString with value {}.'.format(self.str_value))
        stream.seek(0)
        return stream.read()

    def to_element(self, t: ET.Element):
        """
        Takes a t element and adds all the styles as 's' elements.
        This method must only be called from a text object and never for getting a properties value. To get a properties
        value use the 'value' attribute directly.
        :return: the passed in element with the style elements added
        """
        if len(self.style_starts) == 0:
            raise TypeError('Call of to_element on CDXString is invalid if no styles are present. '
                            'If CDXString is part of a property there are no styles.')
        for idx, style in enumerate(self.styles):
            s = style.to_element()
            text_start_index = self.style_starts[idx]
            if len(self.styles) > (idx + 1):
                text_end_index = self.style_starts[(idx+1)]
                txt = self.str_value[text_start_index:text_end_index]
                s.text = txt
            else:
                txt = self.str_value[text_start_index:]
                s.text = txt 
            t.append(s)
            logger.debug("Appended style to t element.")
        return t

    def to_property_value(self) -> str:
        return self.str_value


class CDXFontStyle(CDXType):
    """
    Note about font size:
    Font size, measured in 20ths of a point in cdx. Note that this is an integral field, which implies that CDX files
    cannot store font sizes any more accurately than the nearest 0.05 of a point.
    """

    DEFAULT_FONT_SIZE = 12 * 20

    def __init__(self, font_id, font_type, font_size, font_color):

        self.font_id = font_id
        self.font_type = font_type
        self.font_size = font_size
        self.font_color = font_color

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXFontStyle':

        stream = io.BytesIO(property_bytes)
        font_id = int.from_bytes(stream.read(2), "little")
        font_type = int.from_bytes(stream.read(2), "little")
        font_size = int.from_bytes(stream.read(2), "little")
        font_color = int.from_bytes(stream.read(2), "little")
        return CDXFontStyle(font_id, font_type, font_size, font_color)

    @staticmethod
    def from_element(s: ET.Element) -> 'CDXFontStyle':

        font_id = int(s.attrib["font"])
        # font face is not set in cdxml if plain
        if "face" in s.attrib:
            font_type = int(s.attrib["face"])
        else:
            font_type = 0  # plain
        if "size" in s.attrib:
            font_size = int(float(s.attrib["size"]) * 20)
        else:
            font_size = CDXFontStyle.DEFAULT_FONT_SIZE
        if "color" in s.attrib:
            font_color = int(s.attrib["color"])
        else:
            font_color = 0  # black
        return CDXFontStyle(font_id, font_type, font_size, font_color)

    def font_size_points(self) -> float:
        return self.font_size / 20.0

    def to_bytes(self) -> bytes:

        return self.font_id.to_bytes(2, byteorder='little') + self.font_type.to_bytes(2, byteorder='little') \
            + self.font_size.to_bytes(2, byteorder='little') + self.font_color.to_bytes(2, byteorder='little')

    def to_element(self) -> ET.Element:
        s = ET.Element('s')
        s.attrib['font'] = str(int(self.font_id))
        s.attrib['size'] = str(self.font_size_points())
        s.attrib['face'] = str(self.font_type)
        s.attrib['color'] = str(self.font_color)
        logger.debug("Created element '{}'.".format(ET.tostring(s, encoding='unicode', method='xml')))
        return s

    def to_property_value(self) -> str:
        return 'font="{}" size="{}" face="{}" color="{}"'.format(self.font_id, self.font_size_points(), self.font_type,
                                                                 self.font_color)


class Font(object):

    module_path = Path(__file__).parent
    charsets_path = module_path / 'charsets.yml'
    with open(charsets_path, 'r') as stream:
        CHARSETS = yaml.safe_load(stream)

    def __init__(self, font_id: int, charset: int, font_name: str):

        self.id = font_id
        self.charset = charset
        self.font_name = font_name


class CDXFontTable(CDXType):

    def __init__(self, platform: int, fonts=None):

        if fonts is None:
            fonts = []
        self.platform = platform
        self.fonts = fonts

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXFontTable':
        stream = io.BytesIO(property_bytes)
        platform = int.from_bytes(stream.read(2), "little", signed=False)
        num_fonts = int.from_bytes(stream.read(2), "little", signed=False)
        fonts = []
        for i in range(num_fonts):
            font_id = int.from_bytes(stream.read(2), "little", signed=False)
            charset = int.from_bytes(stream.read(2), "little", signed=False)
            font_name_length = int.from_bytes(stream.read(2), "little", signed=False)
            font_name = stream.read(font_name_length).decode('ascii')
            fonts.append(Font(font_id, charset, font_name))
        return CDXFontTable(platform, fonts)

    @staticmethod
    def from_element(fonttable: ET.Element) -> 'CDXFontTable':

        fonts = []

        for font in fonttable.iter(tag="font"):
            logger.debug("Reading font {}.".format(font.attrib))
            font_id = int(font.attrib["id"])
            charset = next(key for key, value in Font.CHARSETS.items() if value == font.attrib["charset"])
            font_name = font.attrib["name"]
            fonts.append(Font(font_id, charset, font_name))

        # set platform to windows / not defined in cdxml
        return CDXFontTable(0x0001, fonts)

    def to_bytes(self) -> bytes:

        stream = io.BytesIO()
        stream.write(self.platform.to_bytes(2, byteorder='little'))
        # number of fonts
        stream.write(len(self.fonts).to_bytes(2, byteorder='little'))
        for font in self.fonts:
            stream.write(font.id.to_bytes(2, byteorder='little'))
            stream.write(font.charset.to_bytes(2, byteorder='little'))
            stream.write(len(font.font_name).to_bytes(2, byteorder='little'))
            stream.write(font.font_name.encode('ascii'))
        stream.seek(0)
        return stream.read()

    def to_element(self) -> ET.Element:
        ft = ET.Element('fonttable')
        for font in self.fonts:
            f = ET.SubElement(ft, 'font')
            f.attrib['id'] = str(font.id)
            f.attrib['charset'] = Font.CHARSETS[font.charset]
            f.attrib['name'] = font.font_name
        return ft

    def to_property_value(self) -> str:
        return ET.tostring(self.to_element(), encoding='unicode', method='xml')


class Color(object):

    def __init__(self, r: int, g: int, b: int):

        self.r = r
        self.g = g
        self.b = b


class CDXColorTable(CDXType):

    COLOR_MAX_VALUE = 65535

    def __init__(self, colors=None):

        if colors is None:
            colors = []
        self.colors = colors

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXColorTable':
        stream = io.BytesIO(property_bytes)
        num_colors = int.from_bytes(stream.read(2), "little", signed=False)
        colors = []
        for i in range(num_colors):
            r = int.from_bytes(stream.read(2), "little", signed=False)
            g = int.from_bytes(stream.read(2), "little", signed=False)
            b = int.from_bytes(stream.read(2), "little", signed=False)
            colors.append(Color(r, g, b))
        return CDXColorTable(colors)

    @staticmethod
    def from_element(colortable: ET.Element) -> 'CDXColorTable':

        colors = []

        for color in colortable.iter(tag="color"):
            r = int(float(color.attrib["r"]) * CDXColorTable.COLOR_MAX_VALUE)
            g = int(float(color.attrib["g"]) * CDXColorTable.COLOR_MAX_VALUE)
            b = int(float(color.attrib["b"]) * CDXColorTable.COLOR_MAX_VALUE)
            colors.append(Color(r, g, b))

        return CDXColorTable(colors)

    def to_bytes(self) -> bytes:

        stream = io.BytesIO()
        # number of colors
        stream.write(len(self.colors).to_bytes(2, byteorder='little'))
        for color in self.colors:
            stream.write(color.r.to_bytes(2, byteorder='little'))
            stream.write(color.g.to_bytes(2, byteorder='little'))
            stream.write(color.b.to_bytes(2, byteorder='little'))
        stream.seek(0)
        return stream.read()

    def to_element(self) -> ET.Element:
        ct = ET.Element('colortable')
        for color in self.colors:
            c = ET.SubElement(ct, 'color')
            # scale colors as represented as float from 0 to 1 in cdxml
            c.attrib['r'] = str(color.r / CDXColorTable.COLOR_MAX_VALUE)
            c.attrib['g'] = str(color.g / CDXColorTable.COLOR_MAX_VALUE)
            c.attrib['b'] = str(color.b / CDXColorTable.COLOR_MAX_VALUE)
        return ct

    def to_property_value(self) -> str:
        return ET.tostring(self.to_element(), encoding='unicode', method='xml')


class CDXCoordinate(CDXType):
    """
    In CDX files, a CDXCoordinate is an INT32. 1 unit represents 1/65536 points, or 1/4718592 inches, or 1/1857710 cm.
    This permits a drawing space of about 23.1 meters. In contexts where appropriate, 1 unit represents 10-15 meters,
    permitting a coordinate space of approx. ±2.1x10-6 meters (±21,474 Angstroms).

    In CDXML files, a CDXCoordinate is scaled differently, so that 1 unit represents 1 point. CDXCoordinates in CDXML
    files may be represented as decimal values.

    In 2D coordinate spaces, the origin is at the top left corner, and the coordinates increase down and to the right.

    Example: 1 inch (72 points):
    CDX:	00 00 48 00
    CDXML:	"72"

    Note that ChemDraw itself saves cdxml files that contain values that exceed the INT32 limit of cdx files in the
    WindowPosition property. I suspect this is an issue with multi-display setups and it's also not clear  what this
    property is used for. When writing back to cdx, this will get automatically "trimmed" to max allowed value.
    """
    CDXML_CONVERSION_FACTOR = 65536
    CDX_MAX_VALUE = 2147483647
    CDX_MIN_VALUE = -2147483648

    def __init__(self, value: int):
        self.coordinate = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXCoordinate':

        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXCoordinate(value)

    @staticmethod
    def from_string(value: str) -> 'CDXCoordinate':

        units = int(float(value) * CDXCoordinate.CDXML_CONVERSION_FACTOR)
        if units > CDXCoordinate.CDX_MAX_VALUE or units < CDXCoordinate.CDX_MIN_VALUE:
            logger.info("Coordinate value '{}' exceeds maximum or minimum value for cdx files.".format(units))
        return CDXCoordinate(units)

    def to_bytes(self) -> bytes:
        if self.coordinate > CDXCoordinate.CDX_MAX_VALUE:
            logger.warning("Coordinate value '{}' exceeds maximum value for cdx files. "
                           "Reducing value to maximum allowed value.".format(self.coordinate))
            return self.CDX_MAX_VALUE.to_bytes(4, byteorder='little', signed=True)
        elif self.coordinate < CDXCoordinate.CDX_MIN_VALUE:
            logger.warning("Coordinate value '{}' exceeds minimum value for cdx files. "
                           "Reducing value to minimum allowed value.".format(self.coordinate))
            return self.CDX_MIN_VALUE.to_bytes(4, byteorder='little', signed=True)
        else:
            return self.coordinate.to_bytes(4, byteorder='little', signed=True)

    def to_property_value(self) -> str:

        return str(round(self.coordinate / CDXCoordinate.CDXML_CONVERSION_FACTOR, 2))


class CDXPoint2D(CDXType):
    """
    In CDX files, a CDXPoin t2D is an x- and a y-CDXCoordinate stored as a pair of INT32s, y coordinate followed by x
    coordinate.

    In CDXML files, a CDXPoint2D is a stored as a pair of numeric values, x coordinate followed by y coordinate.
    Note that this ordering is different than in CDX files!

    Example: 1 inch (72 points) to the right, and 2 inches down:
    CDX:	00 00 90 00 00 00 48 00
    CDXML:	"72 144"
    """

    def __init__(self, x: CDXCoordinate, y: CDXCoordinate):

        self.x = x
        self.y = y

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXPoint2D':

        y = CDXCoordinate.from_bytes(property_bytes[0:4])
        x = CDXCoordinate.from_bytes(property_bytes[4:8])

        return CDXPoint2D(x, y)

    @staticmethod
    def from_string(value: str) -> 'CDXPoint2D':

        coords = value.split(sep=' ')
        y = CDXCoordinate.from_string(coords[1])
        x = CDXCoordinate.from_string(coords[0])

        return CDXPoint2D(x, y)

    def to_bytes(self) -> bytes:

        return self.y.to_bytes() + self.x.to_bytes()

    def to_property_value(self) -> str:

        return self.x.to_property_value() + " " + self.y.to_property_value()


class CDXPoint3D(CDXType):
    """
    In CDX files, a CDXPoint3D is an x- and a y-CDXCoordinate stored as a pair of INT32s, z coordinate followed by y
    coordinate followed by x coordinate.

    In CDXML files, a CDXPoint2D is a stored as a pair of numeric values, x coordinate followed by y coordinate followed
    by z coordinate. Note that this ordering is different than in CDX files!

    Example: 1 inch (72 points) to the right, 2 inches down, and 3 inches deep:
    CDX:	00 00 d8 00 00 00 90 00 00 00 48 00
    CDXML:	"72 144 216"
    """

    def __init__(self, x: CDXCoordinate, y: CDXCoordinate, z: CDXCoordinate):

        self.x = x
        self.y = y
        self.z = z

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXPoint3D':

        z = CDXCoordinate.from_bytes(property_bytes[0:4])
        y = CDXCoordinate.from_bytes(property_bytes[4:8])
        x = CDXCoordinate.from_bytes(property_bytes[8:12])

        return CDXPoint3D(x, y, z)

    @staticmethod
    def from_string(value: str) -> 'CDXPoint3D':
        coords = value.split(sep=' ')
        z = CDXCoordinate.from_string(coords[2])
        y = CDXCoordinate.from_string(coords[1])
        x = CDXCoordinate.from_string(coords[0])

        return CDXPoint3D(x, y, z)

    def to_bytes(self) -> bytes:

        return self.z.to_bytes() + self.y.to_bytes() + self.x.to_bytes()

    def to_property_value(self) -> str:
        # Spec says z y x for cdx and x y z for cdxml but by looking at cdxml generated from ChemDraw this is
        # clearly wrong. Not sure but I actually think it's x y z for both cases.
        # (hence x value is probably z and vice versa)
        return self.z.to_property_value() + " " + self.y.to_property_value() + " " + self.x.to_property_value()


class CDXRectangle(CDXType):
    """
    In CDX files, rectangles are stored as four CDXCoordinate values, representing, in order: top, left, bottom, and
    right edges of the rectangle.

    In CDXML files, rectangles are stored as four CDXCoordinate values, representing, in order: left, top, right, and
    bottom edges of the rectangle. Note that this ordering is different than in CDX files!

    Example: top: 1 inch, left: 2 inches, bottom: 3 inches, right: 4 inches:
    CDX:	00 00 48 00 00 00 90 00 00 00 D8 00 00 00 20 01
    CDXML:	"144 72 288 216"
    """

    def __init__(self, top: CDXCoordinate, left: CDXCoordinate, bottom: CDXCoordinate, right: CDXCoordinate):

        self.top = top
        self.left = left
        self.bottom = bottom
        self.right = right

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXRectangle':

        top = CDXCoordinate.from_bytes(property_bytes[0:4])
        left = CDXCoordinate.from_bytes(property_bytes[4:8])
        bottom = CDXCoordinate.from_bytes(property_bytes[8:12])
        right = CDXCoordinate.from_bytes(property_bytes[12:16])

        return CDXRectangle(top, left, bottom, right)

    @staticmethod
    def from_string(value: str) -> 'CDXRectangle':
        coords = value.split(sep=' ')
        top = CDXCoordinate.from_string(coords[1])
        left = CDXCoordinate.from_string(coords[0])
        bottom = CDXCoordinate.from_string(coords[3])
        right = CDXCoordinate.from_string(coords[2])

        return CDXRectangle(top, left, bottom, right)

    def to_bytes(self) -> bytes:

        return self.top.to_bytes() + self.left.to_bytes() + self.bottom.to_bytes() + self.right.to_bytes()

    def to_property_value(self) -> str:

        return self.left.to_property_value() + " " + self.top.to_property_value() + " " \
               + self.right.to_property_value() + " " + self.bottom.to_property_value()


class CDXBoolean(CDXType):
    """
    In CDX files, an INT8 value representing True or Yes if non-zero, and False or No if zero.

    In CDXML files, a enumerated value that may be either yes or no.

    Note that this data type actually has a third implied value, 'unknown'. Since CDX and CDXML are both tagged formats,
    any given property may be omitted altogether from the file. A missing property of this type cannot be assumed to be
    either true or false.
    """

    def __init__(self, value: bool):

        self.bool_value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBoolean':
        if len(property_bytes) != 1:
            raise ValueError("A Boolean should be exactly of length 1.")
        if property_bytes == b'\x00':
            return CDXBoolean(False)
        else:
            return CDXBoolean(True)

    @staticmethod
    def from_string(value: str) -> 'CDXBoolean':

        if value == "yes":
            return CDXBoolean(True)
        elif value == "no":
            return CDXBoolean(False)
        else:
            raise ValueError("Found invalid value {} for boolean type. Allowed are 'yes' and 'no'.".format(value))

    def to_bytes(self) -> bytes:
        if self.bool_value:
            return b'\x01'
        else:
            return b'\x00'

    def to_property_value(self) -> str:
        if self.bool_value:
            return "yes"
        else:
            return "no"


class CDXBooleanImplied(CDXType):
    """
    In CDX files, an INT8 value representing True or Yes if present, and False or No if absent.

    Note that properties of this type have zero length in CDX files: the only thing that matters is whether the property
    is or isn't present in the file. In contrast to the CDXBoolean data type (above), if a property of this type is
    missing from the CDX file, its value must be assumed to be False or No.

    In CDXML files, a enumerated value that may be either yes or no.

    I've found cases in which the documentation states a property is boolean implied while it actually is not in
    an example file (FractionalWidths, InterpretChemically)
    """

    def __init__(self, value: bool):

        self.bool_value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBooleanImplied':
        if len(property_bytes) != 0:
            raise ValueError("A BooleanImplied should be 0-length.")
        return CDXBooleanImplied(True)

    @staticmethod
    def from_string(value: str) -> 'CDXBooleanImplied':

        if value == "yes":
            return CDXBooleanImplied(True)
        elif value == "no":
            return CDXBooleanImplied(False)
        else:
            raise ValueError("Found invalid value {} for boolean type. Allowed are 'yes' and 'no'.".format(value))

    def to_bytes(self) -> bytes:
        if not self.bool_value:
            raise ValueError("A BooleanImplied with value 'False' should not be written to cdx file.")
        # empty bytes, see doc comment -> presence marks True value, absence false
        return b''

    def to_property_value(self) -> str:
        if self.bool_value:
            return "yes"
        else:
            return "no"


class CDXObjectIDArray(CDXType):

    def __init__(self, ids: list):
        self.ids = ids

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXObjectIDArray':
        if len(property_bytes) % 4 != 0:
            raise ValueError('CDXObjectIDArray must consist of n*4 bytes. Found {} bytes.'.format(len(property_bytes)))
        array_length = len(property_bytes) // 4
        ids = []
        stream = io.BytesIO(property_bytes)
        for i in range(array_length):
            id = int.from_bytes(stream.read(4), "little", signed=False)
            ids.append(id)
        return CDXObjectIDArray(ids)

    @staticmethod
    def from_string(value: str) -> 'CDXObjectIDArray':
        ids = value.split(sep=' ')
        ids = list(map(int, ids))
        return CDXObjectIDArray(ids)

    def to_bytes(self) -> bytes:
        stream = io.BytesIO()
        for id in self.ids:
            stream.write(id.to_bytes(4, byteorder='little', signed=False))
        stream.seek(0)
        return stream.read()

    def to_property_value(self) -> str:
        return ' '.join(str(x) for x in self.ids)


class CDXAminoAcidTermini(CDXType, Enum):
    """
    This type doesn't exist in spec. It's stored as 1 byte in cdx and in ChemDraw 18 there are 2 possible settings
    which are shown as text in cdxml
    """
    HOH = 1
    NH2COOH = 2

    def __init__(self, value: int):
        if 1 > value > 2:
            raise ValueError("Currently only 2 values allowed: 1 or 2.")
        self.termini = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXAminoAcidTermini':
        if len(property_bytes) != 1:
            raise ValueError("CDXAminoAcidTermini should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=False)
        return CDXAminoAcidTermini(value)

    @staticmethod
    def from_string(value: str) -> 'CDXAminoAcidTermini':
        return CDXAminoAcidTermini[value]

    def to_bytes(self) -> bytes:
        return self.termini.to_bytes(1, byteorder='little', signed=False)

    def to_property_value(self) -> str:
        val = str(CDXAminoAcidTermini(self.termini))
        return val.split('.')[1]


class CDXAutonumberStyle(CDXType, Enum):

    Roman = 0
    Arabic = 1
    Alphabetic = 2

    def __init__(self, value: int):
        if 0 > value > 2:
            raise ValueError("Currently only 3 values allowed: 0-2.")
        self.autonumber_style = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXAutonumberStyle':
        if len(property_bytes) != 1:
            raise ValueError("CDXAutonumberStyle should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=False)
        return CDXAutonumberStyle(value)

    @staticmethod
    def from_string(value: str) -> 'CDXAutonumberStyle':
        return CDXAutonumberStyle[value]

    def to_bytes(self) -> bytes:
        return self.autonumber_style.to_bytes(1, byteorder='little', signed=False)

    def to_property_value(self) -> str:
        val = str(CDXAutonumberStyle(self.autonumber_style))
        return val.split('.')[1]  # only actually value without enum name


class CDXBondSpacing(CDXType):

    def __init__(self, value: int):
        if -32768 > value > 32767:
            raise ValueError("Needs to be a 16-bit int in range -32768 to 32767.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBondSpacing':
        if len(property_bytes) != 2:
            raise ValueError("INT16 should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXBondSpacing(value)

    @staticmethod
    def from_string(value: str) -> 'CDXBondSpacing':
        return CDXBondSpacing(int(float(value) * 10))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        return str(int(self.value / 10))


class CDXDoubleBondPosition(CDXType, Enum):

    Center = 0     # Double bond is centered, but was positioned automatically by the program
    Right = 1      # Double bond is on the right (viewing from the "begin" atom to the "end" atom), but was positioned automatically by the program
    Left = 2       # Double bond is on the left (viewing from the "begin" atom to the "end" atom), but was positioned automatically by the program
    Center_m = 256 # Double bond is centered, and was positioned manually by the user
    Right_m = 257  # Double bond is on the right (viewing from the "begin" atom to the "end" atom), and was positioned manually by the user
    Left_m = 258   # Double bond is on the left (viewing from the "begin" atom to the "end" atom), and was positioned manually by the user

    def __init__(self, value: int):
        if 0 > value > 258:
            raise ValueError("Needs to be in [0,1,2,256,257,258].")
        self.double_bond_position = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXDoubleBondPosition':
        if len(property_bytes) != 2:
            raise ValueError("CDXDoubleBondPosition should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXDoubleBondPosition(value)

    @staticmethod
    def from_string(value: str) -> 'CDXDoubleBondPosition':
        return CDXDoubleBondPosition[value]

    def to_bytes(self) -> bytes:
        return self.double_bond_position.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXDoubleBondPosition(self.double_bond_position))
        val = val.split('.')[1]  # only actually value without enum name
        val = val.replace("_m", "")  # cdxml only has 3 values, hence remove the trailing _m
        return val


class CDXBondDisplay(CDXType, Enum):

    Solid = 0
    Dash = 1
    Hash = 2
    WedgedHashBegin = 3
    WedgedHashEnd = 4
    Bold = 5
    WedgeBegin = 6
    WedgeEnd = 7
    Wavy = 8
    HollowWedgeBegin = 9
    HollowWedgeEnd = 10
    WavyWedgeBegin = 11
    WavyWedgeEnd = 12
    Dot = 13
    DashDot = 14

    def __init__(self, value: int):
        if 0 > value > 14:
            raise ValueError("Needs to be between 0 and 14")
        self.bond_display = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBondDisplay':
        if len(property_bytes) != 2:
            raise ValueError("CDXBondDisplay should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXBondDisplay(value)

    @staticmethod
    def from_string(value: str) -> 'CDXBondDisplay':
        return CDXBondDisplay[value]

    def to_bytes(self) -> bytes:
        return self.bond_display.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXBondDisplay(self.bond_display))
        return val.split('.')[1]  # only actually value without enum name


class CDXAtomStereo(CDXType, Enum):
    """
    This type doesn't exist in spec. It's an enum and making is a separate type makes top level parsing consistent.
    This is an enumerated property. Acceptable values are shown in the following list:
    Value	CDXML Name	Description
    0	U	Undetermined
    1	N	Determined to be symmetric
    2	R	Asymmetric: (R)
    3	S	Asymmetric: (S)
    4	r	Pseudoasymmetric: (r)
    5	s	Pseudoasymmetric: (s)
    6	u	Unspecified: The node is not symmetric (might be asymmetric or pseudoasymmetric), but lacks a hash/wedge so
            absolute configuration cannot be determined

    """

    U = 0
    N = 1
    R = 2
    S = 3
    r = 4
    s = 5
    u = 6

    def __init__(self, value: int):
        if 0 > value > 6:
            raise ValueError("Needs to be between 0-6")
        self.atom_stereo = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXAtomStereo':
        if len(property_bytes) != 1:
            raise ValueError("CDXAtomStereo should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXAtomStereo(value)

    @staticmethod
    def from_string(value: str) -> 'CDXAtomStereo':
        return CDXAtomStereo[value]

    def to_bytes(self) -> bytes:
        return self.atom_stereo.to_bytes(1, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXAtomStereo(self.atom_stereo))
        return val.split('.')[1]  # only actually value without enum name


class CDXBondStereo(CDXType, Enum):
    """
    This type doesn't exist in spec. It's an enum and making is a separate type makes top level parsing consistent.

    This is an enumerated property. Acceptable values are shown in the following list:
    Value	CDXML Name	Description
    0	U	Undetermined
    1	N	Determined to be symmetric
    2	E	Asymmetric: (E)
    3	Z	Asymmetric: (Z)
    """
    U = 0
    N = 1
    E = 2
    Z = 3

    def __init__(self, value: int):
        if 0 > value > 3:
            raise ValueError("Needs to be between 0-3")
        self.bond_stereo = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBondStereo':
        if len(property_bytes) != 1:
            raise ValueError("CDXBondStereo should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXBondStereo(value)

    @staticmethod
    def from_string(value: str) -> 'CDXBondStereo':
        return CDXBondStereo[value]

    def to_bytes(self) -> bytes:
        return self.bond_stereo.to_bytes(1, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXBondStereo(self.bond_stereo))
        return val.split('.')[1]  # only actually value without enum name


class INT8(CDXType):
    """
    This is kind of stupid but makes the upper-level parsing code easier
    """
    def __init__(self, value: int):
        if -128 > value > 127:
            raise ValueError("Needs to be a 16-bit int in range -128 to 127.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'INT8':
        if len(property_bytes) != 1:
            raise ValueError("INT8 should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return INT8(value)

    @staticmethod
    def from_string(value: str) -> 'INT8':
        return INT8(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(1, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        return str(self.value)


class UINT8(CDXType):
    """
    This is kind of stupid but makes the upper-level parsing code easier
    """
    def __init__(self, value: int):
        if 0 > value > 255:
            raise ValueError("Needs to be a 8-bit uint in range 0 to 255.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'UINT8':
        if len(property_bytes) != 1:
            raise ValueError("UINT8 should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=False)
        return UINT8(value)

    @staticmethod
    def from_string(value: str) -> 'UINT8':
        return UINT8(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(1, byteorder='little', signed=False)

    def to_property_value(self) -> str:
        return str(self.value)


class INT16(CDXType):
    """
    This is kind of stupid but makes the upper-level parsing code easier
    """
    def __init__(self, value: int):
        if -32768 > value > 32767:
            raise ValueError("Needs to be a 16-bit int in range -32768 to 32767.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'INT16':
        if len(property_bytes) != 2:
            raise ValueError("INT16 should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return INT16(value)

    @staticmethod
    def from_string(value: str) -> 'INT16':
        return INT16(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        return str(self.value)


class UINT16(CDXType):
    """
    This is kind of stupid but makes the upper-level parsing code easier
    """
    def __init__(self, value: int):
        if 0 > value > 65535:
            raise ValueError("Needs to be a 16-bit uint in range 0 to 65535.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'UINT16':
        if len(property_bytes) != 2:
            raise ValueError("UINT16 should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=False)
        return UINT16(value)

    @staticmethod
    def from_string(value: str) -> 'UINT16':
        return UINT16(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(2, byteorder='little', signed=False)

    def to_property_value(self) -> str:
        return str(self.value)


class INT32(CDXType):
    """
    This is kind of stupid but makes the upper-level parsing code easier
    """
    def __init__(self, value: int):
        if -2147483648 > value > 2147483647:
            raise ValueError("Needs to be a 16-bit int in range -32768 to 32767.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'INT32':
        if len(property_bytes) != 4:
            raise ValueError("INT32 should consist of exactly 4 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return INT32(value)

    @staticmethod
    def from_string(value: str) -> 'INT32':
        return INT32(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(4, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        return str(self.value)


class UINT32(CDXType):
    """
    This is kind of stupid but makes the upper-level parsing code easier
    """
    def __init__(self, value: int):
        if 0 > value > 4294967295:
            raise ValueError("Needs to be a 32-bit uint in range 0 to 4294967295.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'UINT32':
        if len(property_bytes) != 4:
            raise ValueError("INT32 should consist of exactly 4 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=False)
        return UINT32(value)

    @staticmethod
    def from_string(value: str) -> 'UINT32':
        return UINT32(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(4, byteorder='little', signed=False)

    def to_property_value(self) -> str:
        return str(self.value)


class INT16ListWithCounts(CDXType):
    """
    This data type consists of a series of UINT16 values.
    In CDX files, this data type is prefixed by an additional UINT16 value indicating 
    the total number of values to follow.
    """
    def __init__(self, values: list):
        self.values = values

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'INT16ListWithCounts':
        stream = io.BytesIO(property_bytes)
        length = int.from_bytes(stream.read(2), "little", signed=False)
        values = []
        for i in range(length):
            value = int.from_bytes(stream.read(2), "little", signed=False)
            values.append(value)
        return INT16ListWithCounts(values)

    @staticmethod
    def from_string(value: str) -> 'INT16ListWithCounts':
        vals = value.split(sep=' ')
        vals = list(map(int, vals))
        return INT16ListWithCounts(vals)

    def to_bytes(self) -> bytes:
        stream = io.BytesIO()
        length = len(self.values)
        stream.write(length.to_bytes(2, byteorder='little', signed=False))        
        for value in self.values:
            stream.write(value.to_bytes(2, byteorder='little', signed=False)) 
        stream.seek(0)
        return stream.read()
        
    def to_property_value(self) -> str:
        return ' '.join(map(str, self.values))


class Unformatted(CDXType):

    def __init__(self, value: bytes):

        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'Unformatted':
        return Unformatted(property_bytes)

    @staticmethod
    def from_string(value: str) -> 'Unformatted':
        return Unformatted(bytes.fromhex(value))

    def to_bytes(self) -> bytes:
        return self.value

    def to_property_value(self) -> str:
        return self.value.hex()


class CDXBracketUsage(CDXType):
    """
    BracketUsage property is a INT8 enum according to spec. However an example files contained this property as a
    2-byte value where additional byte was 0. So the hacky code in here works around this problem.

    Python doesn't seem to allow having to extend enums when init methods gets more than 1 argument?
    Hence the inner class enum.
    """
    def __init__(self, bracket_usage: int, additional_bytes: bytes = b''):
        self.bracket_usage = bracket_usage
        self.additional_bytes = additional_bytes
        
    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBracketUsage':
        length = len(property_bytes)
        if length > 1:
            logger.warning("Passed bytes value of length {} to CDXBracketUsage which is an INT8 enum and should be "
                           "only 1-byte.".format(length))
        additional_bytes = property_bytes[1:]
        val = property_bytes[0]
        return CDXBracketUsage(val, additional_bytes)

    @staticmethod
    def from_string(value: str) -> 'CDXBracketUsage':
        # return int value and not actual enum instance
        return CDXBracketUsage(CDXBracketUsage.BracketUsage[value].value)

    def to_bytes(self) -> bytes:
        val = self.bracket_usage.to_bytes(1, byteorder='little', signed=True)
        return val + self.additional_bytes

    def to_property_value(self) -> str:
        val = str(CDXBracketUsage.BracketUsage(self.bracket_usage))
        return val.split('.')[1]  # only actually value without enum name

    class BracketUsage(Enum):
        Unspecified = 0
        Unused1 = 1
        Unused2 = 2
        SRU = 3
        Monomer = 4
        Mer = 5
        Copolymer = 6
        CopolymerAlternating = 7
        CopolymerRandom = 8
        CopolymerBlock = 9
        Crosslink = 10
        Graft = 11
        Modification = 12
        Component = 13
        MixtureUnordered = 14
        MixtureOrdered = 15
        MultipleGroup = 16
        Generic = 17
        Anypolymer = 18


class CDXBracketType(CDXType, Enum):

    RoundPair = 0
    SquarePair = 1
    CurlyPair = 2
    Square = 3
    Curly = 4
    Round = 5

    def __init__(self, value: int):
        if 0 > value > 5:
            raise ValueError("Needs to be between 0-5")
        self.bracket_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBracketType':
        if len(property_bytes) != 2:
            raise ValueError("CDXBracketType should consist of exactly 2 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXBracketType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXBracketType':
        return CDXBracketType[value]

    def to_bytes(self) -> bytes:
        return self.bracket_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXBracketType(self.bracket_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXGraphicType(CDXType, Enum):

    Undefined = 0
    Line = 1
    Arc = 2
    Rectangle = 3
    Oval = 4
    Orbital = 5
    Bracket = 6
    Symbol = 7

    def __init__(self, value: int):
        if 0 > value > 7:
            raise ValueError("Needs to be between 0-7")
        self.graphic_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXGraphicType':
        if len(property_bytes) != 2:
            raise ValueError("CDXGraphicType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXGraphicType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXGraphicType':
        return CDXGraphicType[value]

    def to_bytes(self) -> bytes:
        return self.graphic_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXGraphicType(self.graphic_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXArrowType(CDXType, Enum):

    NoHead = 0
    HalfHead = 1
    FullHead = 2
    Resonance = 4
    Equilibrium = 8
    Hollow = 16
    RetroSynthetic = 32
    NoGo = 64
    Dipole = 128

    def __init__(self, value: int):
        if 0 > value > 128:
            raise ValueError("Needs to be between 0-128")
        self.arrow_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXArrowType':
        if len(property_bytes) != 2:
            raise ValueError("CDXArrowType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXArrowType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXArrowType':
        return CDXArrowType[value]

    def to_bytes(self) -> bytes:
        return self.arrow_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXArrowType(self.arrow_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXArrowHeadType(CDXType, Enum):

    Unspecified = 0
    Solid = 1
    Hollow = 2
    Angle = 3

    def __init__(self, value: int):
        if 0 > value > 3:
            raise ValueError("Needs to be between 0-3")
        self.arrow_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXArrowHeadType':
        if len(property_bytes) != 2:
            raise ValueError("CDXArrowheadType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXArrowHeadType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXArrowHeadType':
        return CDXArrowHeadType[value]

    def to_bytes(self) -> bytes:
        return self.arrow_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXArrowHeadType(self.arrow_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXArrowHeadPosition(CDXType, Enum):
    # Does not exist in specification
    # not used yet needs to be fully reverse engineered first
    Unspecified = 0
    Non = 1  # actual value is None but not possible here
    Full = 2
    HalfRight = 4
    HalfLeft = 3

    def __init__(self, value: int):
        if 0 > value > 4:
            raise ValueError("Needs to be between 0-4")
        self.arrow_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXArrowHeadPosition':
        if len(property_bytes) != 2:
            raise ValueError("CDXArrowHeadPosition should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXArrowHeadPosition(value)

    @staticmethod
    def from_string(value: str) -> 'CDXArrowHeadPosition':
        return CDXArrowHeadPosition[value]

    def to_bytes(self) -> bytes:
        return self.arrow_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        if self.arrow_type == 1:
            return "None"
        else:
            val = str(CDXArrowHeadPosition(self.arrow_type))
            return val.split('.')[1]  # only actually value without enum name


class CDXFillType(CDXType, Enum):

    Unspecified = 0x0000
    Non = 0x0001  # actual value is None but not possible here
    Solid = 0x0002
    Shaded = 0x0004
    Gradient = 0x0008
    Pattern = 0x0010

    def __init__(self, value: int):
        if 0 > value > 16:
            raise ValueError("Needs to be between 0-16")
        self.fill_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXFillType':
        if len(property_bytes) != 2:
            raise ValueError("CDXFillType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXFillType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXFillType':
        return CDXFillType[value]

    def to_bytes(self) -> bytes:
        return self.fill_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        if self.fill_type == 1:
            return "None"
        else:
            val = str(CDXFillType(self.fill_type))
            return val.split('.')[1]  # only actually value without enum name


class CDXJustification(CDXType, Enum):

    Right = -1
    Left = 0
    Center = 1
    Full = 2
    Above = 3
    Below = 4
    Auto = 5
    Best = 6

    def __init__(self, value: int):
        if -1 > value > 6:
            raise ValueError("Needs to be between -1 and 6")
        self.label_justification = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXJustification':
        if len(property_bytes) != 1:
            raise ValueError("CDXLabelJustification should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXJustification(value)

    @staticmethod
    def from_string(value: str) -> 'CDXJustification':
        return CDXJustification[value]

    def to_bytes(self) -> bytes:
        return self.label_justification.to_bytes(1, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXJustification(self.label_justification))
        return val.split('.')[1]  # only actually value without enum name


class CDXBondOrder(CDXType, Enum):

    Unspecified = 0xFFFF
    Single = 0x0001
    Double = 0x0002
    Triple = 0x0004
    Quadruple = 0x0008
    Quintuple = 0x0010
    Hextuple = 0x0020
    OneHalf = 0x0040
    OneAndAHalf = 0x0080  # Aromatic
    TwoAndAHalf = 0x0100
    ThreeAndAHalf = 0x0200
    FourAndAHalf = 0x0400
    FiveAndAHalf = 0x0800
    dative = 0x1000
    ionic = 0x2000
    hydrogen = 0x4000
    threecenter = 0x8000

    def __init__(self, value: int):
        self.order = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXBondOrder':
        if len(property_bytes) != 2:
            raise ValueError("CDXBondOrder should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXBondOrder(value)

    @staticmethod
    def from_string(value: str) -> 'CDXBondOrder':
        try:
            v = float(value)
            if v == 1:
                return CDXBondOrder["Single"]
            elif v == 2:
                return CDXBondOrder["Double"]
            elif v == 3:
                return CDXBondOrder["Triple"]
            elif v == 1.5:
                return CDXBondOrder["OneAndAHalf"]
            elif v == 4:
                return CDXBondOrder["Quadruple"]
            elif v == 5:
                return CDXBondOrder["Quintuple"]
            elif v == 6:
                return CDXBondOrder["Hextuple"]
            elif v == 0.5:
                return CDXBondOrder["OneHalf"]
            elif v == 2.5:
                return CDXBondOrder["TwoAndAHalf"]
            elif v == 3.5:
                return CDXBondOrder["ThreeAndAHalf"]
            elif v == 4.5:
                return CDXBondOrder["FourAndAHalf"]
            elif v == 5.5:
                return CDXBondOrder["FiveAndAHalf"]
            elif v == 0xFFFF:
                return CDXBondOrder["Unspecified"]
        except ValueError:
            # use enum name
            return CDXBondOrder[value]

    def to_bytes(self) -> bytes:
        return self.order.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:

        if self.order >= 0x1000:
            val = str(CDXJustification(self.order))
            return val.split('.')[1]  # only actually value without enum name
        elif self.order == 0x0001:
            return "1"
        elif self.order == 0x0002:
            return "2"
        elif self.order == 0x0004:
            return "3"
        elif self.order == 0x0008:
            return "4"
        elif self.order == 0x0010:
            return "5"
        elif self.order == 0x0020:
            return "6"
        elif self.order == 0x0040:
            return "0.5"
        elif self.order == 0x0080:
            return "1.5"
        elif self.order == 0x0100:
            return "2.5"
        elif self.order == 0x0200:
            return "3.5"
        elif self.order == 0x0400:
            return "4.5"
        elif self.order == 0x0800:
            return "5.5"


class CDXLabelAlignment(CDXType, Enum):

    Auto = 0
    Left = 1
    Center = 2
    Right = 3
    Above = 4
    Below = 5
    Best = 6

    def __init__(self, value: int):
        if -1 > value > 6:
            raise ValueError("Needs to be between 0 and 6")
        self.label_alignment = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXLabelAlignment':
        if len(property_bytes) != 1:
            raise ValueError("CDXLabelAlignment should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXLabelAlignment(value)

    @staticmethod
    def from_string(value: str) -> 'CDXLabelAlignment':
        return CDXLabelAlignment[value]

    def to_bytes(self) -> bytes:
        return self.label_alignment.to_bytes(1, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXLabelAlignment(self.label_alignment))
        return val.split('.')[1]  # only actually value without enum name


class CDXLineHeight(CDXType):
    """
    3 Properties use LineHeight: LineHeight (legacy), CaptionLineHeight and LabelLineHeight.
    LineHeight is UINT16 while the other 2 are INT16.
    Assumption: since line height is in point, no value in LineHeight will overflow...
    Values 0 and 1 have special meaning and in CDXML take a string value: 0 -> variable and 1 -> auto
    """
    def __init__(self, value: int):
        if -32768 > value > 32767:
            raise ValueError("Needs to be a 16-bit int in range -32768 to 32767.")
        self.value = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXLineHeight':
        if len(property_bytes) != 2:
            raise ValueError("CDXLineHeight should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXLineHeight(value)

    @staticmethod
    def from_string(value: str) -> 'CDXLineHeight':
        if value == 'auto':
            return CDXLineHeight(1)
        elif value == 'variable':
            return CDXLineHeight(0)
        else:
            return CDXLineHeight(int(value))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        if self.value == 0:
            return 'variable'
        elif self.value == 1:
            return 'auto'
        else:
            return str(self.value)


class CDXAtomGeometry(CDXType, Enum):

    Unknown = 0
    m_1 = 1
    Linear = 2
    Bent = 3
    TrigonalPlanar = 4
    TrigonalPyramidal = 5
    SquarePlanar = 6
    Tetrahedral = 7
    TrigonalBipyramidal = 8
    SquarePyramidal = 9
    m_5 = 10
    Octahedral = 11
    m_6 = 12
    m_7 = 13
    m_8 = 14
    m_9 = 15
    m_10 = 16

    def __init__(self, value: int):
        if -1 > value > 16:
            raise ValueError("Needs to be between 0 and 6")
        self.geometry = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXAtomGeometry':
        if len(property_bytes) != 1:
            raise ValueError("CDXAtomGeometry should consist of exactly 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXAtomGeometry(value)

    @staticmethod
    def from_string(value: str) -> 'CDXAtomGeometry':
        if value.isdigit():
            value = 'm_' + value
        return CDXAtomGeometry[value]

    def to_bytes(self) -> bytes:
        return self.geometry.to_bytes(1, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXAtomGeometry(self.geometry))
        prop_val = val.split('.')[1]  # only actually value without enum name
        return prop_val.replace("m_", "")


class CDXNodeType(CDXType, Enum):

    Unspecified = 0
    Element = 1
    ElementList = 2
    ElementListNickname = 3
    Nickname = 4
    Fragment = 5
    Formula = 6
    GenericNickname = 7
    AnonymousAlternativeGroup = 8
    NamedAlternativeGroup = 9
    MultiAttachment = 10
    VariableAttachment = 11
    ExternalConnectionPoint = 12
    LinkNode = 13

    def __init__(self, value: int):
        if -1 > value > 13:
            raise ValueError("Needs to be between 0 and 13")
        self.node_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXNodeType':
        if len(property_bytes) != 2:
            raise ValueError("CDXNodeType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXNodeType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXNodeType':
        return CDXNodeType[value]

    def to_bytes(self) -> bytes:
        return self.node_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXNodeType(self.node_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXSymbolType(CDXType, Enum):

    LonePair = 0
    Electron = 1
    RadicalCation = 2
    RadicalAnion = 3
    CirclePlus = 4
    CircleMinus = 5
    Dagger = 6
    DoubleDagger = 7
    Plus = 8
    Minus = 9
    Racemic = 10
    Absolute = 11
    Relative = 12
    LonePair_2 = 13

    def __init__(self, value: int):
        if -1 > value > 13:
            raise ValueError("Needs to be between 0 and 13")
        self.symbol_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXSymbolType':
        if len(property_bytes) != 2:
            raise ValueError("CDXSymbolType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXSymbolType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXSymbolType':
        return CDXSymbolType[value]

    def to_bytes(self) -> bytes:
        return self.symbol_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        if self.symbol_type == 13:
            # Specifications mentions LonePair twice as cdxml text value but 2 options in cdx
            return "LonePair"
        else:
            val = str(CDXSymbolType(self.symbol_type))
            return val.split('.')[1]  # only actually value without enum name


class CDXTagType(CDXType, Enum):

    Unknown = 0
    Double = 1
    Long = 2
    String = 3

    def __init__(self, value: int):
        if -1 > value > 3:
            raise ValueError("Needs to be between 0 and 3")
        self.tag_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXTagType':
        if len(property_bytes) != 2:
            raise ValueError("CDXTagType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXTagType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXTagType':
        return CDXTagType[value]

    def to_bytes(self) -> bytes:
        return self.tag_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXTagType(self.tag_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXPositioningType(CDXType, Enum):

    auto = 0
    angle = 1
    offset = 2
    absolute = 3

    def __init__(self, value: int):
        if -1 > value > 3:
            raise ValueError("Needs to be between 0 and 3")
        self.positioning_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXPositioningType':
        if len(property_bytes) != 2:
            raise ValueError("CDXPositioningType should consist of exactly 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXPositioningType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXPositioningType':
        return CDXPositioningType[value]

    def to_bytes(self) -> bytes:
        return self.positioning_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXPositioningType(self.positioning_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXOvalType(CDXType, Enum):

    Circle = 1
    Shaded = 2
    Filled = 4
    Dashed = 8
    Bold = 16
    Shadowed = 32

    def __init__(self, value: int):
        if 1 > value > 32:
            raise ValueError("Needs to be between 1 and 32")
        self.oval_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXOvalType':
        if len(property_bytes) < 1 and len(property_bytes) > 2:
            # Bug in ChemDraw 8 wrote this as only 1-byte (int8) so must allow 1 or 2 bytes
            raise ValueError("CDXOvalType should consist of 1 or 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXOvalType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXOvalType':
        return CDXOvalType[value]

    def to_bytes(self) -> bytes:
        return self.oval_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXPositioningType(self.oval_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXOrbitalType(CDXType, Enum):
    s = 0
    oval = 1
    lobe = 2
    p = 3
    hybridPlus = 4
    hybridMinus = 5
    dz2Plus = 6
    dz2Minus = 7
    dxy = 8
    sShaded = 256
    ovalShaded= 257
    lobeShaded = 258
    pShaded = 259
    sFilled = 512
    ovalFilled = 513
    lobeFilled = 514
    pFilled = 515
    hybridPlusFilled = 516
    hybridMinusFilled = 517
    dz2PlusFilled = 518
    dz2MinusFilled = 519
    dxyFilled = 520

    def __init__(self, value: int):
        if 0 > value > 520:
            raise ValueError("Needs to be between 0 and 520")
        self.orbital_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXOrbitalType':
        if len(property_bytes) != 2:
            raise ValueError("CDXOrbitalType should consist 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXOrbitalType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXOrbitalType':
        return CDXOrbitalType[value]

    def to_bytes(self) -> bytes:
        return self.orbital_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXOrbitalType(self.orbital_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXRectangleType(CDXType, Enum):

    Plain = 0
    RoundEdge = 1
    Shadow = 2
    Shaded = 4
    Filled = 8
    Dashed = 16
    Bold = 32

    def __init__(self, value: int):
        if 0 > value > 32:
            raise ValueError("Needs to be between 0 and 32")
        self.rectangle_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXRectangleType':
        if len(property_bytes) != 2:
            raise ValueError("CDXRectangleType should consist 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXRectangleType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXRectangleType':
        return CDXRectangleType[value]

    def to_bytes(self) -> bytes:
        return self.rectangle_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXRectangleType(self.rectangle_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXLineType(CDXType, Enum):

    Solid = 0
    Dashed = 1
    Bold = 2
    Wavy = 4

    def __init__(self, value: int):
        if 0 > value > 4:
            raise ValueError("Needs to be between 0 and 4")
        self.line_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXLineType':
        if len(property_bytes) != 2:
            raise ValueError("CDXLineType should consist 2 bytes.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXLineType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXLineType':
        return CDXLineType[value]

    def to_bytes(self) -> bytes:
        return self.line_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXLineType(self.line_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXPolymerRepeatPattern(CDXType, Enum):

    HeadToTail = 0
    HeadToHead = 1
    EitherUnknown = 2

    def __init__(self, value: int):
        if 0 > value > 2:
            raise ValueError("Needs to be between 0 and 2")
        self.repeat_pattern = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXPolymerRepeatPattern':
        if len(property_bytes) != 1:
            raise ValueError("CDXPolymerRepeatPattern should consist 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXPolymerRepeatPattern(value)

    @staticmethod
    def from_string(value: str) -> 'CDXPolymerRepeatPattern':
        return CDXPolymerRepeatPattern[value]

    def to_bytes(self) -> bytes:
        return self.repeat_pattern.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXPolymerRepeatPattern(self.repeat_pattern))
        return val.split('.')[1]  # only actually value without enum name


class CDXPolymerFlipType(CDXType, Enum):

    Unspecified = 0
    NoFlip = 1
    Flip = 2

    def __init__(self, value: int):
        if 0 > value > 2:
            raise ValueError("Needs to be between 0 and 2")
        self.flip_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXPolymerFlipType':
        if len(property_bytes) != 1:
            raise ValueError("CDXPolymerFlipType should consist 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXPolymerFlipType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXPolymerFlipType':
        return CDXPolymerFlipType[value]

    def to_bytes(self) -> bytes:
        return self.flip_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXPolymerFlipType(self.flip_type))
        return val.split('.')[1]  # only actually value without enum name


class CDXConstraintType(CDXType, Enum):

    Undefined = 0
    Distance = 1
    Angle = 2
    ExclusionSphere = 3

    def __init__(self, value: int):
        if 0 > value > 3:
            raise ValueError("Needs to be between 0 and 3")
        self.constraint_type = value

    @staticmethod
    def from_bytes(property_bytes: bytes) -> 'CDXConstraintType':
        if len(property_bytes) != 1:
            raise ValueError("CDXConstraintType should consist 1 byte.")
        value = int.from_bytes(property_bytes, "little", signed=True)
        return CDXConstraintType(value)

    @staticmethod
    def from_string(value: str) -> 'CDXConstraintType':
        return CDXConstraintType[value]

    def to_bytes(self) -> bytes:
        return self.constraint_type.to_bytes(2, byteorder='little', signed=True)

    def to_property_value(self) -> str:
        val = str(CDXConstraintType(self.constraint_type))
        return val.split('.')[1]  # only actually value without enum name