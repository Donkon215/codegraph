"""Unit tests for layer assignment system.

Task O-005: Layer detection for all five layer types.
"""

from __future__ import annotations

import pytest

from codegraph.layers import Layer


class TestLayerEnum:
    """Test Layer enum properties."""

    def test_layer_values(self) -> None:
        assert Layer.STDLIB == 0
        assert Layer.EXTERNAL == 1
        assert Layer.INTERNAL_LIB == 2
        assert Layer.PROJECT == 3
        assert Layer.TEST == 4

    def test_modifiable_layers(self) -> None:
        assert not Layer.STDLIB.is_modifiable()
        assert not Layer.EXTERNAL.is_modifiable()
        assert not Layer.INTERNAL_LIB.is_modifiable()
        assert Layer.PROJECT.is_modifiable()
        assert Layer.TEST.is_modifiable()

    def test_ordering(self) -> None:
        assert Layer.STDLIB < Layer.EXTERNAL
        assert Layer.EXTERNAL < Layer.INTERNAL_LIB
        assert Layer.TEST > Layer.PROJECT

    def test_descriptions(self) -> None:
        for layer in Layer:
            desc = layer.description()
            assert isinstance(desc, str)
            assert len(desc) > 0
