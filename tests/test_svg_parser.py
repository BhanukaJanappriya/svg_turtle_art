"""Tests for SVG document parsing."""

from __future__ import annotations

import math

import pytest

from svg_turtle_renderer.core.exceptions import InvalidSVGError
from svg_turtle_renderer.geometry.coordinate_system import BoundingBox
from svg_turtle_renderer.parser.svg_parser import SVGParser, estimate_tolerance


def parse(markup: str, **kwargs):
    """Parse markup, wrapping it in an <svg> root unless it has one."""
    if not markup.lstrip().startswith("<svg"):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' + markup + "</svg>"
        )
    return SVGParser(**kwargs).parse_string(markup)


def only_shape(markup: str, **kwargs):
    """Parse markup that is expected to produce exactly one shape."""
    drawing = parse(markup, **kwargs)
    assert len(drawing.shapes) == 1
    return drawing.shapes[0]


class TestDocumentLoading:
    def test_missing_file_is_reported_clearly(self):
        with pytest.raises(InvalidSVGError, match="File not found"):
            SVGParser().parse_file("does_not_exist.svg")

    def test_a_directory_is_not_a_file(self, tmp_path):
        with pytest.raises(InvalidSVGError, match="Not a file"):
            SVGParser().parse_file(str(tmp_path))

    def test_empty_input_is_rejected(self):
        with pytest.raises(InvalidSVGError, match="empty"):
            SVGParser().parse_string("   ")

    def test_malformed_xml_is_reported(self):
        with pytest.raises(InvalidSVGError, match="not well-formed"):
            SVGParser().parse_string("<svg><rect></svg>")

    def test_a_non_svg_root_is_rejected(self):
        with pytest.raises(InvalidSVGError, match="expected <svg>"):
            SVGParser().parse_string("<html><body/></html>")

    def test_a_valid_but_empty_svg_yields_no_shapes(self):
        assert parse("").shapes == []

    def test_parses_from_a_real_file(self, svg_file):
        path = svg_file(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="5" height="5" fill="red"/></svg>'
        )
        assert len(SVGParser().parse_file(path).shapes) == 1

    def test_documents_without_a_namespace_still_parse(self):
        # Hand-written SVG often omits xmlns; browsers cope, so this must too.
        drawing = SVGParser().parse_string(
            '<svg viewBox="0 0 10 10"><rect width="5" height="5"/></svg>'
        )
        assert len(drawing.shapes) == 1


class TestViewport:
    def test_reads_the_viewbox(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 300 200"/>'
        )
        assert drawing.viewbox == BoundingBox(10, 20, 310, 220)

    def test_width_and_height_fall_back_to_the_viewbox(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200"/>'
        )
        assert (drawing.width, drawing.height) == (300, 200)

    def test_a_viewbox_is_derived_from_width_and_height(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"/>'
        )
        assert drawing.viewbox == BoundingBox(0, 0, 300, 200)

    def test_units_on_width_and_height_are_converted(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="1in"/>'
        )
        assert drawing.viewbox.width == pytest.approx(96)

    def test_a_document_with_no_viewport_uses_the_svg_default(self):
        drawing = SVGParser().parse_string('<svg xmlns="http://www.w3.org/2000/svg"/>')
        assert drawing.viewbox == BoundingBox(0, 0, 300, 150)

    def test_commas_are_allowed_in_the_viewbox(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0,0,50,50"/>'
        )
        assert drawing.viewbox.width == 50

    def test_a_malformed_viewbox_falls_back_rather_than_crashing(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="nonsense" width="80" height="40"/>'
        )
        assert drawing.viewbox == BoundingBox(0, 0, 80, 40)

    def test_a_zero_size_viewbox_is_rejected(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 0" width="10" height="10"/>'
        )
        assert drawing.viewbox == BoundingBox(0, 0, 10, 10)


class TestBasicShapes:
    def test_rect(self):
        shape = only_shape('<rect x="10" y="20" width="30" height="40" fill="red"/>')
        assert shape.subpaths[0].points == [(10, 20), (40, 20), (40, 60), (10, 60)]
        assert shape.subpaths[0].closed

    def test_a_zero_size_rect_draws_nothing(self):
        assert parse('<rect width="0" height="10"/>').shapes == []

    def test_rounded_rect_has_curved_corners(self):
        shape = only_shape('<rect width="100" height="50" rx="10" fill="red"/>')
        # Far more points than a plain rectangle's four.
        assert shape.vertex_count > 10
        # No point may escape the rectangle's own bounds.
        bounds = shape.bounds()
        assert bounds.min_x >= -1e-6
        assert bounds.max_x <= 100 + 1e-6

    def test_rx_alone_supplies_ry(self):
        one = only_shape('<rect width="100" height="50" rx="10" fill="red"/>')
        both = only_shape('<rect width="100" height="50" rx="10" ry="10" fill="red"/>')
        assert one.vertex_count == both.vertex_count

    def test_corner_radius_is_capped_at_half_the_side(self):
        # rx=500 on a 100-wide rect must clamp to 50, giving a stadium shape,
        # not geometry that escapes the rectangle.
        shape = only_shape('<rect width="100" height="50" rx="500" fill="red"/>')
        assert shape.bounds().max_x <= 100 + 1e-6

    def test_circle(self):
        shape = only_shape('<circle cx="50" cy="50" r="25" fill="red"/>')
        for x, y in shape.subpaths[0].points:
            assert math.dist((x, y), (50, 50)) == pytest.approx(25, abs=0.5)

    def test_a_zero_radius_circle_draws_nothing(self):
        assert parse('<circle cx="5" cy="5" r="0"/>').shapes == []

    def test_ellipse(self):
        shape = only_shape('<ellipse cx="50" cy="50" rx="40" ry="20" fill="red"/>')
        bounds = shape.bounds()
        assert bounds.width == pytest.approx(80, abs=0.5)
        assert bounds.height == pytest.approx(40, abs=0.5)

    def test_line(self):
        shape = only_shape('<line x1="0" y1="0" x2="10" y2="10" stroke="black"/>')
        assert shape.subpaths[0].points == [(0, 0), (10, 10)]
        assert not shape.subpaths[0].closed

    def test_a_zero_length_line_draws_nothing(self):
        assert parse('<line x1="5" y1="5" x2="5" y2="5" stroke="black"/>').shapes == []

    def test_polygon_is_closed(self):
        shape = only_shape('<polygon points="0,0 10,0 5,10" fill="red"/>')
        assert shape.subpaths[0].closed
        assert shape.subpaths[0].points == [(0, 0), (10, 0), (5, 10)]

    def test_polyline_is_open(self):
        shape = only_shape('<polyline points="0,0 10,0 5,10" stroke="black"/>')
        assert not shape.subpaths[0].closed

    def test_an_odd_trailing_coordinate_is_dropped(self):
        shape = only_shape('<polyline points="0,0 10,0 5" stroke="black"/>')
        assert shape.subpaths[0].points == [(0, 0), (10, 0)]

    def test_path(self):
        shape = only_shape('<path d="M 0 0 L 10 10" stroke="black"/>')
        assert shape.subpaths[0].points == [(0, 0), (10, 10)]

    def test_a_shape_with_no_paint_is_skipped(self):
        assert parse('<rect width="10" height="10" fill="none"/>').shapes == []


class TestPaint:
    def test_fill_defaults_to_black(self):
        # SVG's initial fill is black, so a rect with no fill attribute is
        # black, not invisible.
        shape = only_shape('<rect width="10" height="10"/>')
        assert shape.style.fill.as_hex() == "#000000"

    def test_stroke_defaults_to_none(self):
        assert only_shape('<rect width="10" height="10"/>').style.stroke is None

    def test_fill_none_means_no_fill(self):
        shape = only_shape('<rect width="10" height="10" fill="none" stroke="red"/>')
        assert shape.style.fill is None

    def test_the_style_attribute_overrides_presentation_attributes(self):
        shape = only_shape('<rect width="10" height="10" fill="red" style="fill: blue"/>')
        assert shape.style.fill.as_hex() == "#0000ff"

    def test_style_declarations_are_parsed(self):
        shape = only_shape(
            '<rect width="10" height="10" style="fill:red;stroke:blue;stroke-width:3"/>'
        )
        assert shape.style.fill.as_hex() == "#ff0000"
        assert shape.style.stroke.as_hex() == "#0000ff"
        assert shape.style.stroke_width == 3

    def test_fill_opacity_lands_on_the_colour(self):
        shape = only_shape('<rect width="10" height="10" fill="red" fill-opacity="0.5"/>')
        assert shape.style.fill.a == pytest.approx(0.5)

    def test_element_opacity_multiplies_into_both_paints(self):
        shape = only_shape('<rect width="10" height="10" fill="red" stroke="blue" opacity="0.5"/>')
        assert shape.style.fill.a == pytest.approx(0.5)
        assert shape.style.stroke.a == pytest.approx(0.5)

    def test_fully_transparent_paint_is_dropped(self):
        assert parse('<rect width="10" height="10" fill="red" opacity="0"/>').shapes == []

    def test_current_color_resolves_from_an_ancestor(self):
        shape = only_shape('<g color="red"><rect width="10" height="10" fill="currentColor"/></g>')
        assert shape.style.fill.as_hex() == "#ff0000"

    def test_a_line_is_never_filled(self):
        # Even an explicit fill cannot fill a line; it has no interior.
        shape = only_shape('<line x1="0" y1="0" x2="10" y2="0" fill="red" stroke="blue"/>')
        assert shape.style.fill is None


class TestInheritance:
    def test_fill_is_inherited_from_a_group(self):
        shape = only_shape('<g fill="red"><rect width="10" height="10"/></g>')
        assert shape.style.fill.as_hex() == "#ff0000"

    def test_a_child_overrides_its_group(self):
        shape = only_shape('<g fill="red"><rect width="10" height="10" fill="blue"/></g>')
        assert shape.style.fill.as_hex() == "#0000ff"

    def test_inheritance_passes_through_nested_groups(self):
        shape = only_shape('<g fill="red"><g><g><rect width="10" height="10"/></g></g></g>')
        assert shape.style.fill.as_hex() == "#ff0000"

    def test_group_opacity_accumulates(self):
        shape = only_shape(
            '<g opacity="0.5"><g opacity="0.5"><rect width="10" height="10" fill="red"/></g></g>'
        )
        assert shape.style.fill.a == pytest.approx(0.25)

    def test_display_none_hides_a_subtree(self):
        assert parse('<g display="none"><rect width="10" height="10" fill="red"/></g>').shapes == []

    def test_visibility_hidden_hides_a_subtree(self):
        assert parse('<rect width="10" height="10" fill="red" visibility="hidden"/>').shapes == []

    def test_stroke_width_is_inherited(self):
        shape = only_shape('<g stroke="red" stroke-width="5"><rect width="10" height="10"/></g>')
        assert shape.style.stroke_width == 5


class TestTransforms:
    def test_a_transform_is_baked_into_the_geometry(self):
        shape = only_shape('<rect width="10" height="10" fill="red" transform="translate(5, 5)"/>')
        assert shape.subpaths[0].points[0] == pytest.approx((5, 5))

    def test_group_transforms_accumulate(self):
        shape = only_shape(
            '<g transform="translate(10, 0)"><g transform="translate(0, 20)">'
            '<rect width="10" height="10" fill="red"/></g></g>'
        )
        assert shape.subpaths[0].points[0] == pytest.approx((10, 20))

    def test_the_root_svg_transform_applies(self):
        drawing = SVGParser().parse_string(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
            'transform="translate(5,5)">'
            '<rect width="10" height="10" fill="red"/></svg>'
        )
        assert drawing.shapes[0].subpaths[0].points[0] == pytest.approx((5, 5))

    def test_a_scale_transform_scales_the_stroke_width(self):
        shape = only_shape(
            '<rect width="10" height="10" stroke="red" stroke-width="2" transform="scale(3)"/>'
        )
        assert shape.style.stroke_width == pytest.approx(6)

    def test_a_rotation_leaves_the_stroke_width_alone(self):
        shape = only_shape(
            '<rect width="10" height="10" stroke="red" stroke-width="2" transform="rotate(45)"/>'
        )
        assert shape.style.stroke_width == pytest.approx(2)


class TestDefsAndUse:
    def test_defs_are_not_rendered_where_they_are_defined(self):
        assert parse('<defs><rect width="10" height="10" fill="red"/></defs>').shapes == []

    def test_use_instantiates_a_referenced_shape(self):
        shape = only_shape(
            '<defs><rect id="box" width="10" height="10" fill="red"/></defs><use href="#box"/>'
        )
        assert shape.subpaths[0].points[0] == pytest.approx((0, 0))

    def test_use_applies_its_x_and_y_as_a_translation(self):
        shape = only_shape(
            '<defs><rect id="box" width="10" height="10" fill="red"/></defs>'
            '<use href="#box" x="20" y="30"/>'
        )
        assert shape.subpaths[0].points[0] == pytest.approx((20, 30))

    def test_use_applies_its_own_transform(self):
        shape = only_shape(
            '<defs><rect id="box" width="10" height="10" fill="red"/></defs>'
            '<use href="#box" transform="scale(2)"/>'
        )
        assert shape.subpaths[0].points[2] == pytest.approx((20, 20))

    def test_the_legacy_xlink_href_still_works(self):
        shape = only_shape(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'viewBox="0 0 100 100">'
            '<defs><rect id="box" width="10" height="10" fill="red"/></defs>'
            '<use xlink:href="#box" x="5" y="5"/></svg>'
        )
        assert shape.subpaths[0].points[0] == pytest.approx((5, 5))

    def test_each_use_is_an_independent_instance(self):
        drawing = parse(
            '<defs><rect id="box" width="10" height="10" fill="red"/></defs>'
            '<use href="#box" x="0"/><use href="#box" x="50"/>'
        )
        assert len(drawing.shapes) == 2
        assert drawing.shapes[1].subpaths[0].points[0] == pytest.approx((50, 0))

    def test_use_inherits_style_from_its_own_context(self):
        shape = only_shape(
            '<defs><rect id="box" width="10" height="10"/></defs>'
            '<g fill="blue"><use href="#box"/></g>'
        )
        assert shape.style.fill.as_hex() == "#0000ff"

    def test_use_can_reference_a_group(self):
        drawing = parse(
            '<defs><g id="pair"><rect width="5" height="5" fill="red"/>'
            '<rect x="10" width="5" height="5" fill="red"/></g></defs><use href="#pair"/>'
        )
        assert len(drawing.shapes) == 2

    def test_use_can_reference_a_symbol(self):
        drawing = parse(
            '<defs><symbol id="s"><rect width="5" height="5" fill="red"/></symbol></defs>'
            '<use href="#s" x="10"/>'
        )
        assert drawing.shapes[0].subpaths[0].points[0] == pytest.approx((10, 0))

    def test_an_unknown_reference_is_skipped(self):
        assert parse('<use href="#nothing"/>').shapes == []

    def test_an_external_reference_is_skipped(self):
        assert parse('<use href="other.svg#box"/>').shapes == []

    def test_a_circular_reference_terminates(self):
        # Without a cycle guard this would recurse forever.
        drawing = parse(
            '<defs><g id="a"><use href="#b"/></g><g id="b"><use href="#a"/></g></defs>'
            '<use href="#a"/>'
        )
        assert drawing.shapes == []


class TestSwitch:
    def test_a_switch_renders_only_its_first_viable_child(self):
        # A group would render both; a switch must pick one.
        drawing = parse(
            '<switch><rect width="10" height="10" fill="red"/>'
            '<rect width="10" height="10" fill="blue"/></switch>'
        )
        assert len(drawing.shapes) == 1
        assert drawing.shapes[0].style.fill.as_hex() == "#ff0000"

    def test_a_child_demanding_an_extension_is_passed_over(self):
        drawing = parse(
            '<switch><rect width="10" height="10" fill="red" requiredExtensions="urn:x"/>'
            '<rect width="10" height="10" fill="blue"/></switch>'
        )
        assert len(drawing.shapes) == 1
        assert drawing.shapes[0].style.fill.as_hex() == "#0000ff"

    def test_an_empty_conditional_value_fails(self):
        drawing = parse(
            '<switch><rect width="10" height="10" fill="red" systemLanguage=""/>'
            '<rect width="10" height="10" fill="blue"/></switch>'
        )
        assert drawing.shapes[0].style.fill.as_hex() == "#0000ff"

    def test_a_switch_with_no_viable_child_renders_nothing(self):
        assert (
            parse(
                "<switch>"
                '<rect width="10" height="10" fill="red" requiredExtensions="urn:x"/>'
                "</switch>"
            ).shapes
            == []
        )

    def test_a_switch_transform_still_applies(self):
        shape = only_shape(
            '<switch transform="translate(5,5)"><rect width="10" height="10" fill="red"/></switch>'
        )
        assert shape.subpaths[0].points[0] == pytest.approx((5, 5))


class TestClipping:
    def test_a_clip_path_crops_a_shape(self):
        shape = only_shape(
            '<clipPath id="c"><rect x="0" y="0" width="5" height="100"/></clipPath>'
            '<rect width="100" height="100" fill="red" clip-path="url(#c)"/>'
        )
        assert shape.bounds().max_x == pytest.approx(5)

    def test_a_shape_entirely_outside_its_clip_disappears(self):
        assert (
            parse(
                '<clipPath id="c"><rect x="0" y="0" width="5" height="5"/></clipPath>'
                '<rect x="50" y="50" width="10" height="10" fill="red" clip-path="url(#c)"/>'
            ).shapes
            == []
        )

    def test_a_shape_inside_its_clip_is_untouched(self):
        shape = only_shape(
            '<clipPath id="c"><rect width="100" height="100"/></clipPath>'
            '<rect x="10" y="10" width="10" height="10" fill="red" clip-path="url(#c)"/>'
        )
        assert shape.bounds() == BoundingBox(10, 10, 20, 20)

    def test_an_open_polyline_is_clipped(self):
        shape = only_shape(
            '<clipPath id="c"><rect width="50" height="100"/></clipPath>'
            '<polyline points="0,50 100,50" stroke="red" clip-path="url(#c)"/>'
        )
        assert shape.bounds().max_x == pytest.approx(50)

    def test_an_unknown_clip_reference_leaves_the_shape_alone(self):
        shape = only_shape('<rect width="10" height="10" fill="red" clip-path="url(#missing)"/>')
        assert shape.bounds() == BoundingBox(0, 0, 10, 10)

    def test_clip_path_elements_are_not_rendered_themselves(self):
        drawing = parse('<clipPath id="c"><rect width="5" height="5"/></clipPath>')
        assert drawing.shapes == []


class TestUnsupportedContent:
    def test_text_is_skipped_rather_than_crashing(self):
        assert parse('<text x="0" y="0">hello</text>').shapes == []

    def test_a_gradient_fill_leaves_the_shape_unpainted(self):
        # A paint server cannot be honoured, and inventing a flat colour would be
        # a silent lie, so the shape is dropped.
        assert (
            parse(
                '<defs><linearGradient id="g"/></defs><rect width="10" height="10" fill="url(#g)"/>'
            ).shapes
            == []
        )

    def test_unsupported_siblings_do_not_stop_supported_ones(self):
        drawing = parse('<text x="0" y="0">hi</text><rect width="10" height="10" fill="red"/>')
        assert len(drawing.shapes) == 1

    def test_metadata_is_ignored_silently(self, caplog):
        parse("<title>t</title><desc>d</desc><metadata/>")
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_an_unsupported_element_warns_only_once(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            parse("<text>a</text><text>b</text><text>c</text>")
        assert len([r for r in caplog.records if "text" in r.message]) == 1


class TestStrictMode:
    def test_a_bad_path_is_skipped_when_not_strict(self):
        drawing = parse('<path d="M 0 0 Q" fill="red"/><rect width="10" height="10" fill="red"/>')
        assert len(drawing.shapes) == 1

    def test_a_bad_path_raises_in_strict_mode(self):
        from svg_turtle_renderer.core.exceptions import PathSyntaxError

        with pytest.raises(PathSyntaxError):
            parse('<path d="M 0 0 Q" fill="red"/>', strict=True)


class TestTolerance:
    def test_tolerance_scales_with_the_viewbox(self):
        small = estimate_tolerance(BoundingBox(0, 0, 10, 10), 1.0)
        large = estimate_tolerance(BoundingBox(0, 0, 1000, 1000), 1.0)
        assert large > small

    def test_higher_resolution_means_a_tighter_tolerance(self):
        coarse = estimate_tolerance(BoundingBox(0, 0, 100, 100), 0.5)
        fine = estimate_tolerance(BoundingBox(0, 0, 100, 100), 4.0)
        assert fine < coarse

    def test_a_degenerate_viewbox_does_not_divide_by_zero(self):
        assert estimate_tolerance(BoundingBox(0, 0, 0, 0), 1.0) > 0

    def test_resolution_drives_vertex_count(self):
        markup = '<circle cx="50" cy="50" r="40" fill="red"/>'
        coarse = parse(markup, resolution=0.25).vertex_count
        fine = parse(markup, resolution=4.0).vertex_count
        assert fine > coarse

    def test_an_explicit_tolerance_overrides_resolution(self):
        markup = '<circle cx="50" cy="50" r="40" fill="red"/>'
        assert (
            parse(markup, tolerance=10.0).vertex_count < parse(markup, tolerance=0.01).vertex_count
        )
