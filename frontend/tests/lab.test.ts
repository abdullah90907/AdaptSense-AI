import { describe, expect, it } from 'vitest';
import { eligibleCutoffs } from '../src/labApi';

const victoria = { context: 56, horizon: 7, season: 7, origins: 36, lookback: 6, evolution: true };

describe('experiment cutoff validation', () => {
  it('reserves complete training, validation, and unseen target blocks', () => {
    expect(eligibleCutoffs(365, victoria)).toEqual({ first: 105, last: 112, required: 358 });
    expect(eligibleCutoffs(358, victoria)).toEqual({ first: 105, last: 105, required: 358 });
    expect(eligibleCutoffs(357, victoria)).toEqual({ first: 105, last: 104, required: 358 });
  });

  it('allows earlier cutoffs for two-candidate replay', () => {
    expect(eligibleCutoffs(365, { ...victoria, evolution: false })).toEqual({ first: 55, last: 112, required: 308 });
  });

  it('rejects settings outside backend constraints', () => {
    expect(eligibleCutoffs(365, { ...victoria, lookback: 36 })).toBeNull();
    expect(eligibleCutoffs(365, { ...victoria, season: 56 })).toBeNull();
    expect(eligibleCutoffs(365, { ...victoria, horizon: 7.5 })).toBeNull();
  });
});
