import test from 'node:test';
import assert from 'node:assert/strict';
import {isDue, nextLabel} from '../src/model.js';
test('manual mode never triggers, even after a missed week', () => assert.equal(isDue(700000, 0, 0), false));
test('first enable and overdue resume trigger one change', () => {
    assert.equal(isDue(100, 0, 86400), true);
    assert.equal(isDue(86499, 100, 86400), false);
    assert.equal(isDue(86500, 100, 86400), true);
});
test('retry delay prevents requests each timer tick', () => {
    assert.equal(isDue(1000, 0, 3600, 1900), false);
    assert.equal(isDue(1900, 0, 3600, 1900), true);
});
test('clock moving backward does not suspend rotation indefinitely', () => assert.equal(isDue(100, 1000, 3600), true));
test('manual and initial schedule labels', () => {
    assert.equal(nextLabel(0, 0), 'Manual changes only');
    assert.equal(nextLabel(0, 3600), 'Due now');
});
