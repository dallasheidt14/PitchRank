/** Current-model dependencies; historical experiments retain their own pinned inventories. */
export const PREDICTOR_SOURCE_FILES = [
  'matchPredictor.ts',
  'confidenceEngine.ts',
  'teamAge.ts',
  'matchPredictionService.ts',
  'predictionIdentity.ts',
  'calibrationLoader.ts',
  'matchEvidence.ts',
];
export const PREDICTOR_CALIBRATION_FILES = {
  ageGroups: 'age_group_parameters.json',
  probability: 'probability_parameters.json',
  margin: 'margin_parameters_v2.json',
  outcome: 'heuristic_outcome_calibration.json',
  confidence: 'confidence_parameters_v2.json',
};

/** Verify input construction separately, preserving existing algorithm signatures. */
export const PREDICTOR_INPUT_SOURCE_FILES = ['utils.ts', 'constants.ts'];
