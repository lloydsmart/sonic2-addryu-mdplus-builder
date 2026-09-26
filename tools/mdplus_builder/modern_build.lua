-- Keep independent assembler evidence while preserving upstream cleanup and
-- failure detection. Run only in a freshly prepared generated checkout.
local remove = os.remove
os.remove = function(path)
    if path == "s2.p" or path == "s2.h" then
        local input = io.open(path, "rb")
        if input then
            local output = assert(io.open("forge-" .. path, "wb"))
            output:write(input:read("*a"))
            output:close()
            input:close()
        end
    end
    return remove(path)
end
dofile("build.lua")
