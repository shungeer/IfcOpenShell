# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Thomas Krijnen <thomas@aecgeeks.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.


import os
import sys
import operator

from .. import ifcopenshell_wrapper
from ..file import file
from ..entity_instance import entity_instance

from . import has_occ

from typing import TypeVar, Union, Optional, Generator, Any

T = TypeVar("T")
ShapeElementType = Union[
    ifcopenshell_wrapper.BRepElement, ifcopenshell_wrapper.TriangulationElement, ifcopenshell_wrapper.SerializedElement
]
ShapeType = Union[ifcopenshell_wrapper.BRep, ifcopenshell_wrapper.Triangulation, ifcopenshell_wrapper.Serialization]


def wrap_shape_creation(settings, shape):
    return shape


if has_occ:
    from . import occ_utils as utils

    try:
        from OCC.Core import TopoDS
    except ImportError:
        from OCC import TopoDS

    def wrap_shape_creation(settings, shape):
        if getattr(settings, "use_python_opencascade", False):
            return utils.create_shape_from_serialization(shape)
        else:
            return shape

class missing_setting:
    def __repr__(self): return '-'

class settings_mixin:  
    """
    Pythonic interface mixin to the settings modules and
    to provide an additional setting to enable pythonOCC
    when available
    """

    USE_PYTHON_OPENCASCADE = 'USE_PYTHON_OPENCASCADE'

    def __init__(self, **kwargs):
        super(settings_mixin, self).__init__()
        for k, v in kwargs.items():
            self.set(getattr(self, k), v)

    def __repr__(self):
        def safe_get(x):
            try: return self.get_(x)
            except: return missing_setting()
        fmt_pair = lambda x: "%s = %r" % (self.rname(x), safe_get(x))
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join(map(fmt_pair, self.setting_names()))
        )
        
    @staticmethod
    def name(k):
        return k.lower().replace('_', '-')
        
    @staticmethod
    def rname(k):
        return k.upper().replace('-', '_')
    
    def set(self, k: str, v: Any) -> None:
        """
        Set value of the setting named `k` to `v`.

        :raises RuntimeError: If there is no setting with name `k`.
        """
        if k == "USE_PYTHON_OPENCASCADE":
            if not has_occ:
                raise AttributeError("Python OpenCASCADE is not installed")
            if v:
                self.set_("iterator-output", ifcopenshell_wrapper.SERIALIZED)
                self.set_("use-world-coords", True)
                self.use_python_opencascade = True
        else:
            self.set_(self.name(k), v)
        
    def get(self, k: str) -> Any:
        """
        Return value of the setting named `k`.

        :raises RuntimeError: If there is no setting with name `k`.
        """
        
        return self.get_(self.name(k))

    def __getattr__(self, k):
        if k in map(self.rname, self.setting_names()):
            return k
        else:
            raise AttributeError("'Settings' object has no attribute '%s'" % k)


class serializer_settings(settings_mixin, ifcopenshell_wrapper.SerializerSettings):
    pass

class settings(settings_mixin, ifcopenshell_wrapper.Settings):
    pass

class iterator(ifcopenshell_wrapper.Iterator):
    def __init__(
        self,
        settings: settings,
        file_or_filename: Union[file, str],
        num_threads: int = 1,
        include: Optional[Union[list[entity_instance],list[str]]] = None,
        exclude: Optional[Union[list[entity_instance],list[str]]] = None,
        geometry_library: str = "opencascade"
    ):
        self.settings = settings
        if isinstance(file_or_filename, file):
            file_or_filename = file_or_filename.wrapped_data
        else:
            # Makes sure people are able to use python's platform agnostic paths
            file_or_filename = os.path.abspath(file_or_filename)

        if include is not None and exclude is not None:
            raise ValueError("include and exclude cannot be specified simultaneously")

        if include is not None or exclude is not None:
            # Couldn't get the typemaps properly applied using %extend so we
            # replicate the SWIG-generated __init__ call on the output of a
            # free function.
            # @todo verify this works with SWIG 4

            include_or_exclude = include if exclude is None else exclude
            include_or_exclude_type = set(x.__class__.__name__ for x in include_or_exclude)

            if include_or_exclude_type == {"entity_instance"}:
                if not all(inst.is_a("IfcProduct") for inst in include_or_exclude):
                    raise ValueError("include and exclude need to be an aggregate of IfcProduct")

                initializer = ifcopenshell_wrapper.construct_iterator_with_include_exclude_id

                include_or_exclude = [i.id() for i in include_or_exclude]
            else:
                initializer = ifcopenshell_wrapper.construct_iterator_with_include_exclude

            self.this = initializer(
                geometry_library, self.settings, file_or_filename, include_or_exclude, include is not None, num_threads
            )
        else:
            ifcopenshell_wrapper.Iterator.__init__(self, geometry_library, settings, file_or_filename, num_threads)

    if has_occ:

        def get(self):
            return wrap_shape_creation(self.settings, ifcopenshell_wrapper.Iterator.get(self))

    def __iter__(self) -> Generator[ShapeElementType, None, None]:
        if self.initialize():
            while True:
                yield self.get()
                if not self.next():
                    break


class tree(ifcopenshell_wrapper.tree):
    def __init__(self, file: Optional[file] = None, settings: Optional[settings] = None):
        args = [self]
        if file is not None:
            args.append(file.wrapped_data)
            if settings is not None:
                args.append(settings)
        ifcopenshell_wrapper.tree.__init__(*args)

    def add_file(self, file: file, settings: settings) -> None:
        ifcopenshell_wrapper.tree.add_file(self, file.wrapped_data, settings)

    def add_iterator(self, iterator: iterator) -> None:
        ifcopenshell_wrapper.tree.add_file(self, iterator)

    def select(
        self,
        value: Union[
            entity_instance, ifcopenshell_wrapper.BRepElement, tuple[float, float, float], "TopoDS.TopoDS_Shape"
        ],
        **kwargs,
    ) -> list[entity_instance]:
        def unwrap(value):
            if isinstance(value, entity_instance):
                return value.wrapped_data
            elif all(map(lambda v: hasattr(value, v), "XYZ")):
                return value.X(), value.Y(), value.Z()
            return value

        args = [self, unwrap(value)]
        if isinstance(value, (entity_instance, ifcopenshell_wrapper.BRepElement)):
            args.append(kwargs.get("completely_within", False))
            if "extend" in kwargs:
                args.append(kwargs["extend"])
        elif isinstance(value, (list, tuple)) and len(value) == 3 and set(map(type, value)) == {float}:
            if "extend" in kwargs:
                args.append(kwargs["extend"])
        elif has_occ:
            if isinstance(value, TopoDS.TopoDS_Shape):
                args[1] = utils.serialize_shape(value)
                args.append(kwargs.get("completely_within", False))
                if "extend" in kwargs:
                    args.append(kwargs["extend"])
        return [entity_instance(e) for e in ifcopenshell_wrapper.tree.select(*args)]

    def select_box(self, value, **kwargs) -> list[entity_instance]:
        def unwrap(value):
            if isinstance(value, entity_instance):
                return value.wrapped_data
            elif hasattr(value, "Get"):
                return value.Get()[:3], value.Get()[3:]
            return value

        args = [self, unwrap(value)]
        if "extend" in kwargs or "completely_within" in kwargs:
            args.append(kwargs.get("completely_within", False))
        if "extend" in kwargs:
            args.append(kwargs.get("extend", -1.0e-5))
        return [entity_instance(e) for e in ifcopenshell_wrapper.tree.select_box(*args)]

    def clash_intersection_many(self, set_a, set_b, tolerance=0.002, check_all=True):
        args = [self, [e.wrapped_data for e in set_a], [e.wrapped_data for e in set_b], tolerance, check_all]
        return ifcopenshell_wrapper.tree.clash_intersection_many(*args)

    def clash_collision_many(self, set_a, set_b, allow_touching=False):
        args = [self, [e.wrapped_data for e in set_a], [e.wrapped_data for e in set_b], allow_touching]
        return ifcopenshell_wrapper.tree.clash_collision_many(*args)

    def clash_clearance_many(self, set_a, set_b, clearance=0.05, check_all=False):
        args = [self, [e.wrapped_data for e in set_a], [e.wrapped_data for e in set_b], clearance, check_all]
        return ifcopenshell_wrapper.tree.clash_clearance_many(*args)


def create_shape(
    settings: settings, inst: entity_instance, repr: Optional[entity_instance] = None
) -> ShapeElementType:
    """
    Return a geometric representation from STEP-based IFCREPRESENTATIONSHAPE
    or
    Return an OpenCASCADE BRep if settings.USE_PYTHON_OPENCASCADE == True

    Note that in Python, you must store a reference to the element returned by this function to prevent garbage
    collection when you access its children. See #1124.

    example:

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_PYTHON_OPENCASCADE, True)

    ifc_file = ifcopenshell.open(file_path)
    products = ifc_file.by_type("IfcProduct")

    for i, product in enumerate(products):
        if product.Representation is not None:
            try:
                created_shape = geom.create_shape(settings, inst=product)
                shape = created_shape.geometry # see #1124
                shape_gpXYZ = shape.Location().Transformation().TranslationPart() # These are methods of the TopoDS_Shape class from pythonOCC
                print(shape_gpXYZ.X(), shape_gpXYZ.Y(), shape_gpXYZ.Z()) # These are methods of the gpXYZ class from pythonOCC
            except:
                print("Shape creation failed")
    """
    return wrap_shape_creation(
        settings,
        ifcopenshell_wrapper.create_shape(settings, inst.wrapped_data, repr.wrapped_data if repr is not None else None),
    )


def consume_iterator(it, with_progress=False):
    if it.initialize():
        while True:
            if with_progress:
                yield it.progress(), it.get()
            else:
                yield it.get()
            if not it.next():
                break


def iterate(settings, file_or_filename, num_threads=1, include=None, exclude=None, with_progress=False, cache=None):
    it = iterator(settings, file_or_filename, num_threads, include, exclude)
    if cache:
        hdf5_cache = serializers.hdf5(cache, settings)
        it.set_cache(hdf5_cache)
    yield from consume_iterator(it, with_progress=with_progress)


def make_shape_function(fn):
    def entity_instance_or_none(e):
        return None if e is None else entity_instance(e)

    if has_occ:

        def _(schema, string_or_shape, *args):
            if isinstance(string_or_shape, TopoDS.TopoDS_Shape):
                string_or_shape = utils.serialize_shape(string_or_shape)
            return entity_instance_or_none(fn(schema, string_or_shape, *args))

    else:

        def _(schema, string, *args):
            return entity_instance_or_none(fn(schema, string, *args))

    return _


serialise = make_shape_function(ifcopenshell_wrapper.serialise)
tesselate = make_shape_function(ifcopenshell_wrapper.tesselate)


def wrap_buffer_creation(fn: T):
    """
    Python does not have automatic casts. The C++ serializers accept a stream_or_filename
    which in C++ can be automatically constructed from a filename string. In Python we
    have to implement this cast/construction explicitly.
    """

    def transform_string(v):
        if isinstance(v, str):
            return ifcopenshell_wrapper.buffer(v)
        else:
            return v

    def inner(*args) -> T:
        return fn(*map(transform_string, args))

    return inner


class serializers:
    obj = wrap_buffer_creation(ifcopenshell_wrapper.WaveFrontOBJSerializer)
    svg = wrap_buffer_creation(ifcopenshell_wrapper.SvgSerializer)
    # Hdf- Xml- and glTF- serializers don't support writing to a buffer, only to filename
    # so no wrap_buffer_creation() for these serializers
    xml = ifcopenshell_wrapper.XmlSerializer
    buffer = ifcopenshell_wrapper.buffer
    # gltf and hdf5 availability depend on IfcOpenShell configuration settings
    try:
        gltf = ifcopenshell_wrapper.GltfSerializer
    except:
        pass
    try:
        hdf5 = ifcopenshell_wrapper.HdfSerializer
    except:
        pass
