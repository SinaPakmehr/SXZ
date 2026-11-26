//! Optional native SXZ anchor scanner. It identifies candidate offsets only;
//! the Python encoder still verifies the full reference match.

use std::slice;

#[inline]
fn bucket(key: u64, mask: usize) -> usize {
    let mixed = (key ^ (key >> 33)).wrapping_mul(0xff51afd7ed558ccd);
    ((mixed ^ (mixed >> 33)) as usize) & mask
}

#[no_mangle]
pub extern "C" fn sxz_anchor_abi() -> u32 {
    1
}

/// ABI: caller owns valid buffers for all given lengths. The table is an
/// open-addressed, power-of-two table of nonzero little-endian 8-byte keys.
#[no_mangle]
pub unsafe extern "C" fn sxz_anchor_scan(
    data: *const u8,
    len: usize,
    start: usize,
    stop: usize,
    table: *const u64,
    slots: usize,
    hits: *mut usize,
    capacity: usize,
) -> usize {
    if len < 8 || !slots.is_power_of_two() || capacity == 0 || start >= stop {
        return 0;
    }
    let input = unsafe { slice::from_raw_parts(data, len) };
    let table = unsafe { slice::from_raw_parts(table, slots) };
    let hits = unsafe { slice::from_raw_parts_mut(hits, capacity) };
    let mut used = 0;
    let mask = slots - 1;
    for index in start..stop.min(len - 7) {
        let ptr = unsafe { input.as_ptr().add(index).cast::<u64>() };
        let key = u64::from_le(unsafe { ptr.read_unaligned() });
        if key == 0 {
            continue;
        }
        let mut slot = bucket(key, mask);
        for _ in 0..slots {
            let value = table[slot];
            if value == 0 {
                break;
            }
            if value == key {
                hits[used] = index;
                used += 1;
                if used == capacity {
                    return used;
                }
                break;
            }
            slot = (slot + 1) & mask;
        }
    }
    used
}
