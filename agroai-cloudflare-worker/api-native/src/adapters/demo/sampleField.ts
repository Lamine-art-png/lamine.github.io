import type { EarthDailyRawInput } from "../../schemas/earthdaily";

export const SAMPLE_FIELD: EarthDailyRawInput["field"] = {
  field_id: "madera-almonds-block-12",
  field_name: "Madera Almonds Block 12",
  grower_id: "agroai-demo-grower",
  farm_id: "madera-demo-farm",
  crop_type: "almonds",
  crop_stage: "mid-season",
  acreage: 120.4,
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-120.1347, 36.9521],
        [-120.1212, 36.9524],
        [-120.1206, 36.9448],
        [-120.1342, 36.9444],
        [-120.1347, 36.9521],
      ],
    ],
  },
  timezone: "America/Los_Angeles",
  region: "Madera County, California",
  soil_profile: {
    texture: "sandy loam",
    awc_mm_per_m: 145,
    rooting_depth_m: 1.15,
    field_capacity: 0.31,
    wilting_point: 0.13,
  },
};

export const SAMPLE_FIELD_CARD = {
  mode: "demo" as const,
  field_id: SAMPLE_FIELD.field_id,
  field_name: SAMPLE_FIELD.field_name,
  crop_type: SAMPLE_FIELD.crop_type,
  crop_stage: SAMPLE_FIELD.crop_stage,
  acreage: SAMPLE_FIELD.acreage,
  region: SAMPLE_FIELD.region,
  freshness: "updated 8 hours ago",
};

