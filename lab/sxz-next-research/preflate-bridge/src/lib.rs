use preflate_rs::{PreflateConfig, preflate_whole_deflate_stream, recreate_whole_deflate_stream};
use std::{panic::catch_unwind, slice};

const LIMIT: usize = 8 << 20;

// Caller provides valid disjoint buffers. Copies out so ownership stays local.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn split(
    source: *const u8, n: usize, output: *mut u8, cap: usize,
) -> usize {
    catch_unwind(|| {
        if n > LIMIT { return 0; }
        let data = unsafe { slice::from_raw_parts(source, n) };
        let config = PreflateConfig {
            max_chain_length: 1024, plain_text_limit: LIMIT, verify_compression: true,
        };
        let Ok((result, plain)) = preflate_whole_deflate_stream(data, &config) else {
            return 0;
        };
        let body = plain.text();
        let corr = &result.corrections;
        let size = 4 + body.len() + corr.len();
        if result.compressed_size != n || size > cap { return 0; }
        let out = unsafe { slice::from_raw_parts_mut(output, cap) };
        out[..4].copy_from_slice(&(body.len() as u32).to_le_bytes());
        out[4..4 + body.len()].copy_from_slice(body);
        out[4 + body.len()..size].copy_from_slice(corr);
        size
    }).unwrap_or(0)
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rejoin(
    source: *const u8, n: usize, output: *mut u8, cap: usize,
) -> usize {
    catch_unwind(|| {
        if !(4..=2*LIMIT).contains(&n) || cap > LIMIT { return 0; }
        let data = unsafe { slice::from_raw_parts(source, n) };
        let size = u32::from_le_bytes(data[..4].try_into().unwrap()) as usize;
        if size > LIMIT || size + 4 >= n { return 0; }
        let Ok(body) = recreate_whole_deflate_stream(&data[4..4 + size], &data[4 + size..]) else {
            return 0;
        };
        if body.len() != cap { return 0; }
        unsafe { slice::from_raw_parts_mut(output, cap) }.copy_from_slice(&body);
        cap
    }).unwrap_or(0)
}
