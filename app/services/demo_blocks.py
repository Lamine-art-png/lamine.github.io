from app.schemas.demo import DemoBlock

# Public / neutral demo blocks only
DEMO_BLOCKS = [
    DemoBlock(
        id="napa_vineyard_a",
        label="Napa Vineyard A (public test block)",
        lat=38.5025,
        lon=-122.2654,
        crop="grape",
        acres=10,
        soil_type="loam",
        region="Napa, CA",
    ),
    DemoBlock(
        id="cv_almond_b",
        label="Central Valley Almond Block B (public test block)",
        lat=36.603,
        lon=-119.451,
        crop="almond",
        acres=40,
        soil_type="silt",
        region="Central Valley, CA",
    ),
    DemoBlock(
        id="paso_vineyard_c",
        label="Paso Robles Vineyard C (public test block)",
        lat=35.626,
        lon=-120.691,
        crop="grape",
        acres=18,
        soil_type="clay",
        region="Paso Robles, CA",
    ),
]

def list_demo_blocks():
    return DEMO_BLOCKS

def get_block(block_id: str) -> DemoBlock:
    for b in DEMO_BLOCKS:
        if b.id == block_id:
            return b
    raise KeyError(f"Unknown demo block: {block_id}")

