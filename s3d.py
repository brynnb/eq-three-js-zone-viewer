from buffer import Buffer
from zlib import decompress


def readS3D(fp):
    b = Buffer(fp)
    offset = b.uint()
    assert b.read(4) == b"PFS "

    filelist = []
    b.pos = offset
    count = b.uint()
    directory = None
    for i in range(count):
        b.pos = offset + 4 + i * 12
        crc, foff, size = b.uint(), b.uint(), b.uint()
        fp.seek(foff)

        data = b""
        while len(data) < size:
            deflen, inflen = b.uint(), b.uint()
            data += decompress(b.read(deflen))
        if crc == 0x61580AC9:
            directory = data
        else:
            filelist.append((foff, data))

    filelist.sort(key=lambda x: x[0])

    assert directory is not None
    b = Buffer(directory)
    assert b.uint() == len(filelist)
    files = {}
    for _, data in filelist:
        fn = b.read(b.uint()).strip(b"\0").decode("utf-8", errors="ignore")
        files[fn.lower()] = data
    return files
