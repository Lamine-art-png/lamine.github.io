import test from 'node:test';
import assert from 'node:assert/strict';
import { generateRecommendation } from '../js/services/recommendationEngine.js';

test('recommendation output with weather context', () => {
  const rec = generateRecommendation(
    { name:'Field 1', crop:'Maize', acreage:10, soilType:'Loam', irrigationMethod:'Drip', lastIrrigationAt:new Date(Date.now()-96*3600000).toISOString(), dataSource:'controller', waterStressLevel:'moderate' },
    { forecastSummary:'Hot and dry', heatRisk:'elevated', frostRisk:'low', rainfallForecastMm:1 }
  );
  assert.ok(rec.mainRecommendation);
  assert.equal(rec.urgency, 'high');
  assert.ok(rec.reasonSummary.length > 1);
});

test('recommendation output highlights missing data', () => {
  const rec = generateRecommendation(
    { name:'Field 1', crop:'Maize', acreage:10, soilType:'', irrigationMethod:'Drip', lastIrrigationAt:null, dataSource:'neither', waterStressLevel:'moderate' },
    { forecastSummary:'Hot and dry', heatRisk:'elevated', frostRisk:'low', rainfallForecastMm:0 }
  );
  assert.equal(rec.confidence, 'moderate');
  assert.ok(rec.missingData.includes('soil type'));
});

test('irrigation log changing recommendation state lowers urgency', () => {
  const before = generateRecommendation(
    { name:'Field 1', crop:'Maize', acreage:10, soilType:'Loam', irrigationMethod:'Drip', lastIrrigationAt:new Date(Date.now()-120*3600000).toISOString(), dataSource:'controller', waterStressLevel:'moderate' },
    { forecastSummary:'Stable', heatRisk:'low', frostRisk:'low', rainfallForecastMm:0 }
  );
  const after = generateRecommendation(
    { name:'Field 1', crop:'Maize', acreage:10, soilType:'Loam', irrigationMethod:'Drip', lastIrrigationAt:new Date().toISOString(), dataSource:'controller', waterStressLevel:'moderate' },
    { forecastSummary:'Stable', heatRisk:'low', frostRisk:'low', rainfallForecastMm:0 }
  );
  assert.notEqual(before.urgency, after.urgency);
});
