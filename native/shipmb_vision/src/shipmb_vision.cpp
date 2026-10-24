#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#endif

#include "shipmb_vision.h"
#include "image_rgb.h"
#include "sha256.hpp"

#include "llama.h"
#include "mtmd.h"
#include "mtmd-helper.h"
#include "json.hpp"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <list>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#if defined(__APPLE__)
#include <sys/sysctl.h>
#elif defined(_WIN32)
#include <windows.h>
#endif

namespace {

constexpr const char *kMissingWeights =
    "Vision weights are not installed. Run `shipmblang setup --vision`.";
constexpr const char *kLlmName = "MiniCPM-V-4_6-Q4_K_M.gguf";
constexpr const char *kMmprojName = "mmproj-model-q8_0.gguf";
constexpr int kFastLongSide = 448;
constexpr int kDefaultCtx = 4096;
constexpr int kDefaultMaxTokens = 16;
constexpr size_t kPrefixLimit = 4;
constexpr size_t kPrefixBytes = 256ull * 1024ull * 1024ull;

thread_local std::string g_error;
thread_local std::string g_result;

void quiet_log(enum ggml_log_level, const char *, void *) {}

struct Prefix {
    std::vector<uint8_t> data;
    llama_pos n_past = 0;
};

int physical_cores() {
#if defined(__linux__)
    {
        std::vector<std::pair<int, int>> seen;
        for (int cpu = 0;; ++cpu) {
            std::string base = "/sys/devices/system/cpu/cpu" + std::to_string(cpu) + "/topology/";
            std::ifstream pkg(base + "physical_package_id");
            std::ifstream core(base + "core_id");
            if (!pkg || !core) break;
            int package_id = -1, core_id = -1;
            pkg >> package_id;
            core >> core_id;
            if (!pkg || !core) break;
            if (std::find(seen.begin(), seen.end(), std::make_pair(package_id, core_id)) == seen.end()) seen.push_back({package_id, core_id});
        }
        if (!seen.empty()) return (int)seen.size();
    }
#elif defined(__APPLE__)
    {
        int cores = 0;
        size_t sz = sizeof cores;
        if (sysctlbyname("hw.physicalcpu", &cores, &sz, nullptr, 0) == 0 && cores > 0) return cores;
    }
#elif defined(_WIN32)
    {
        DWORD length = 0;
        GetLogicalProcessorInformation(nullptr, &length);
        if (length) {
            std::vector<unsigned char> buf(length);
            if (GetLogicalProcessorInformation(reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION>(buf.data()), &length)) {
                int cores = 0;
                auto *info = reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION>(buf.data());
                size_t count = length / sizeof(*info);
                for (size_t i = 0; i < count; ++i) if (info[i].Relationship == RelationProcessorCore) ++cores;
                if (cores > 0) return cores;
            }
        }
    }
#endif
    unsigned fallback = std::thread::hardware_concurrency();
    return fallback ? (int)fallback : 1;
}

#if defined(_WIN32)
std::wstring utf8_to_wide(const std::string &text) {
    if (text.empty()) return {};
    int chars = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), (int)text.size(), nullptr, 0);
    if (chars <= 0) chars = MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0);
    if (chars <= 0) return {};
    std::wstring wide(chars, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), wide.data(), chars);
    return wide;
}

std::string wide_to_utf8(const std::wstring &wide) {
    if (wide.empty()) return {};
    int bytes = WideCharToMultiByte(CP_UTF8, 0, wide.data(), (int)wide.size(), nullptr, 0, nullptr, nullptr);
    if (bytes <= 0) return {};
    std::string out(bytes, '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), (int)wide.size(), out.data(), bytes, nullptr, nullptr);
    return out;
}

std::optional<std::filesystem::path> windows_env_path(const wchar_t *name) {
    DWORD length = GetEnvironmentVariableW(name, nullptr, 0);
    if (length == 0) return std::nullopt;
    std::wstring value(length, L'\0');
    DWORD written = GetEnvironmentVariableW(name, value.data(), length);
    if (written == 0) return std::nullopt;
    value.resize(written);
    if (value.empty()) return std::nullopt;
    return std::filesystem::path(value);
}
#endif

std::filesystem::path path_from_utf8(const std::string &text) {
#if defined(_WIN32)
    std::wstring wide = utf8_to_wide(text);
    if (wide.empty() && !text.empty()) throw std::runtime_error("Vision path is not valid UTF-8.");
    return std::filesystem::path(wide);
#else
    return std::filesystem::path(text);
#endif
}

std::string display_path(const std::filesystem::path &path) {
#if defined(_WIN32)
    return wide_to_utf8(path.wstring());
#else
    return path.string();
#endif
}

// ggml_fopen and stb_image open UTF-8 via _wfopen on Windows. The \\?\ prefix
// is what lets those calls pass MAX_PATH when long-path policy is off.
// Python's setup writes the same prefix for the cache files.
std::filesystem::path extended_path(const std::filesystem::path &input) {
#if defined(_WIN32)
    namespace fs = std::filesystem;
    std::error_code error;
    fs::path absolute = fs::absolute(input, error);
    if (error) absolute = input;
    std::wstring wide = absolute.wstring();
    if (wide.rfind(L"\\\\?\\", 0) == 0) return fs::path(wide);
    if (wide.size() >= 2 && wide[0] == L'\\' && wide[1] == L'\\') {
        return fs::path(std::wstring(L"\\\\?\\UNC\\") + wide.substr(2));
    }
    if (wide.size() >= 2 && wide[1] == L':') return fs::path(std::wstring(L"\\\\?\\") + wide);
    return absolute;
#else
    return input;
#endif
}

std::string utf8_open_path(const std::filesystem::path &input) {
#if defined(_WIN32)
    return wide_to_utf8(extended_path(input).wstring());
#else
    return input.string();
#endif
}

std::filesystem::path default_model_dir() {
    namespace fs = std::filesystem;
#if defined(_WIN32)
    if (auto dir = windows_env_path(L"SHIPMB_VISION_MODEL_DIR")) return *dir;
    if (auto local = windows_env_path(L"LOCALAPPDATA")) return *local / "shipmblang" / "vision";
    if (auto user = windows_env_path(L"USERPROFILE")) return *user / "AppData" / "Local" / "shipmblang" / "vision";
    return fs::path("shipmblang") / "vision";
#else
    if (const char *env = std::getenv("SHIPMB_VISION_MODEL_DIR")) {
        if (*env) return fs::path(env);
    }
#if defined(__APPLE__)
    const char *home = std::getenv("HOME");
    return fs::path(home ? home : ".") / "Library" / "Caches" / "shipmblang" / "vision";
#else
    if (const char *xdg = std::getenv("XDG_CACHE_HOME")) {
        if (*xdg) return fs::path(xdg) / "shipmblang" / "vision";
    }
    const char *home = std::getenv("HOME");
    return fs::path(home ? home : ".") / ".cache" / "shipmblang" / "vision";
#endif
#endif
}

void ensure_backend() {
    static std::once_flag once;
    std::call_once(once, [] {
#if defined(_WIN32)
        // A pipe makes the MSVC CRT fully buffer stderr, so an abort drops the message.
        setvbuf(stderr, nullptr, _IONBF, 0);
#endif
        llama_log_set(quiet_log, nullptr);
        mtmd_helper_log_set(quiet_log, nullptr);
        ggml_backend_load_all();
        llama_backend_init();
    });
}

#if defined(_WIN32)
constexpr SIZE_T kVisionStackBytes = 8u * 1024u * 1024u;

template <typename Fn>
struct VisionCall {
    Fn *fn = nullptr;
    std::optional<decltype(std::declval<Fn &>()())> result;
    std::exception_ptr error;
};

template <typename Fn>
DWORD WINAPI vision_call_thunk(LPVOID raw) {
    auto *call = static_cast<VisionCall<Fn> *>(raw);
    try {
        call->result.emplace((*call->fn)());
    } catch (...) {
        call->error = std::current_exception();
    }
    return 0;
}

// Model load and the vision graph run std::regex and deep C++ frames. The Windows
// default reserve is 1 MiB and the overflow is reported as an access violation.
// CreateThread from this DLL uses the host executable's reserve unless the
// reservation is passed explicitly, so Python's stack is not large enough.
template <typename Fn>
auto run_on_vision_stack(Fn &&fn) -> decltype(fn()) {
    VisionCall<Fn> call;
    call.fn = &fn;
    HANDLE thread = CreateThread(nullptr, kVisionStackBytes, vision_call_thunk<Fn>, &call, STACK_SIZE_PARAM_IS_A_RESERVATION, nullptr);
    if (!thread) return std::forward<Fn>(fn)();
    DWORD wait = WaitForSingleObject(thread, INFINITE);
    CloseHandle(thread);
    if (wait != WAIT_OBJECT_0) throw std::runtime_error("Vision worker failed to finish.");
    if (call.error) std::rethrow_exception(call.error);
    if (!call.result) throw std::runtime_error("Vision worker returned no result.");
    return std::move(*call.result);
}
#else
template <typename Fn>
auto run_on_vision_stack(Fn &&fn) -> decltype(fn()) {
    return std::forward<Fn>(fn)();
}
#endif

std::string runtime_json() {
    ensure_backend();
    nlohmann::json backends = nlohmann::json::array();
    for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(i);
        const char *name = dev ? ggml_backend_dev_name(dev) : nullptr;
        if (name) backends.push_back(name);
    }
    nlohmann::json out = {
        {"llama", "b11846"},
        {"commit", "1a24df163920a4744a95373d178d790b72a9bb2f"},
        {"backends", backends},
    };
    return out.dump();
}

struct Engine {
    llama_model *model = nullptr;
    llama_context *ctx = nullptr;
    mtmd_context *mctx = nullptr;
    llama_sampler *sampler = nullptr;
    int threads = 1;
    int n_ctx = kDefaultCtx;
    int max_tokens = kDefaultMaxTokens;
    bool detailed = false;
    std::string model_hash;
    std::mutex mu;
    std::list<std::string> order;
    std::unordered_map<std::string, Prefix> prefixes;

    ~Engine() {
        if (sampler) llama_sampler_free(sampler);
        if (mctx) mtmd_free(mctx);
        if (ctx) llama_free(ctx);
        if (model) llama_model_free(model);
    }

    void remember(const std::string &key, Prefix prefix) {
        auto found = prefixes.find(key);
        if (found != prefixes.end()) {
            found->second = std::move(prefix);
            order.remove(key);
            order.push_front(key);
            return;
        }
        while (order.size() >= kPrefixLimit) {
            prefixes.erase(order.back());
            order.pop_back();
        }
        order.push_front(key);
        prefixes.emplace(key, std::move(prefix));
    }

    std::string query(const std::string &image_path, const std::string &question, const nlohmann::json &options, smb_vision_token_fn on_token, void *user) {
        std::lock_guard<std::mutex> lock(mu);
        if (question.find('\0') != std::string::npos) throw std::runtime_error("The vision question contains NUL.");
        if (question.size() > 4000) throw std::runtime_error("The vision question is too long.");
        const char *marker = mtmd_default_marker();
        if (question.find(marker) != std::string::npos) throw std::runtime_error("The vision question contains the media marker.");
        bool detailed_query = options.value("detailed", detailed);
        bool embed_only = options.value("embed_only", false);
        int predict = options.value("max_tokens", max_tokens);
        if (predict < 1) predict = 1;
        if (predict > 256) predict = 256;

        namespace fs = std::filesystem;
        fs::path path = path_from_utf8(image_path);
        fs::path opened = extended_path(path);
        if (!fs::is_regular_file(opened)) throw std::runtime_error("Vision image was not found.");
        std::string opened_utf8 = utf8_open_path(path);
        std::string image_sha = sha256_file(opened_utf8);

        smb_rgb decoded{};
        char err[256];
        if (smb_rgb_decode_file(opened_utf8.c_str(), &decoded, err, sizeof err)) throw std::runtime_error(err);
        smb_rgb owned = decoded;
        smb_rgb resized{};
        if (!detailed_query) {
            if (smb_rgb_resize_long_side(&decoded, kFastLongSide, &resized, err, sizeof err)) {
                smb_rgb_free(&decoded);
                throw std::runtime_error(err);
            }
            smb_rgb_free(&decoded);
            owned = resized;
        }
        struct RgbGuard {
            smb_rgb *image;
            ~RgbGuard() { smb_rgb_free(image); }
        } guard{&owned};

        auto started = std::chrono::steady_clock::now();
        mtmd_bitmap *bitmap = mtmd_bitmap_init((uint32_t)owned.width, (uint32_t)owned.height, owned.data);
        if (!bitmap) throw std::runtime_error("Vision could not prepare the image.");
        struct BitmapGuard {
            mtmd_bitmap *bitmap;
            ~BitmapGuard() { if (bitmap) mtmd_bitmap_free(bitmap); }
        } bitmap_guard{bitmap};

        std::string prompt = std::string("<|im_start|>user\n") + marker + "\n" + question +
                             "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n";
        mtmd_input_chunks *chunks = mtmd_input_chunks_init();
        struct ChunkGuard {
            mtmd_input_chunks *chunks;
            ~ChunkGuard() { if (chunks) mtmd_input_chunks_free(chunks); }
        } chunk_guard{chunks};
        mtmd_input_text text{prompt.c_str(), prompt.size(), true, true};
        const mtmd_bitmap *bitmaps[] = {bitmap};
        int tok = mtmd_tokenize(mctx, chunks, &text, bitmaps, 1);
        if (tok) throw std::runtime_error("Vision could not tokenize the image prompt.");

        size_t nch = mtmd_input_chunks_size(chunks);
        if (nch == 0) throw std::runtime_error("Vision produced no input.");
        bool last_is_text = mtmd_input_chunk_get_type(mtmd_input_chunks_get(chunks, nch - 1)) == MTMD_INPUT_CHUNK_TYPE_TEXT;
        int image_tokens = 0;
        for (size_t i = 0; i < nch; ++i) {
            const mtmd_input_chunk *chunk = mtmd_input_chunks_get(chunks, i);
            if (mtmd_input_chunk_get_type(chunk) == MTMD_INPUT_CHUNK_TYPE_IMAGE)
                image_tokens += (int)mtmd_input_chunk_get_n_tokens(chunk);
        }

        if (embed_only) {
            const int n_embd = llama_model_n_embd(model);
            std::vector<float> embeddings;
            for (size_t i = 0; i < nch; ++i) {
                const mtmd_input_chunk *chunk = mtmd_input_chunks_get(chunks, i);
                if (mtmd_input_chunk_get_type(chunk) != MTMD_INPUT_CHUNK_TYPE_IMAGE) continue;
                if (mtmd_encode_chunk(mctx, chunk)) throw std::runtime_error("Vision encode failed.");
                float *embd = mtmd_get_output_embd(mctx);
                if (!embd) throw std::runtime_error("Vision encode returned no embeddings.");
                int ntok = (int)mtmd_input_chunk_get_n_tokens(chunk);
                embeddings.insert(embeddings.end(), embd, embd + (size_t)n_embd * (size_t)ntok);
            }
            double elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
            nlohmann::json out = {
                {"ok", true},
                {"text", ""},
                {"tokens", 0},
                {"image_tokens", image_tokens},
                {"cached", false},
                {"elapsed_ms", elapsed},
                {"detailed", detailed_query},
                {"n_embd", n_embd},
                {"embeddings", embeddings},
            };
            return out.dump();
        }

        llama_memory_clear(llama_get_memory(ctx), true);
        llama_sampler_reset(sampler);
        std::string key = model_hash + "\n" + image_sha + "\n" + (detailed_query ? "d" : "f");
        size_t start = 0;
        llama_pos n_past = 0;
        bool cached = false;
        if (last_is_text && nch >= 2) {
            auto found = prefixes.find(key);
            if (found != prefixes.end()) {
                size_t restored = llama_state_seq_set_data(ctx, found->second.data.data(), found->second.data.size(), 0);
                if (restored) {
                    n_past = found->second.n_past;
                    start = nch - 1;
                    cached = true;
                    order.remove(key);
                    order.push_front(key);
                }
            }
        }

        for (size_t i = start; i < nch; ++i) {
            const mtmd_input_chunk *chunk = mtmd_input_chunks_get(chunks, i);
            bool last = i + 1 == nch;
            auto type = mtmd_input_chunk_get_type(chunk);
            if (type == MTMD_INPUT_CHUNK_TYPE_TEXT) {
                if (mtmd_helper_eval_chunk_single(mctx, ctx, chunk, n_past, 0, 2048, last, &n_past))
                    throw std::runtime_error("Vision text prefill failed.");
            } else if (type == MTMD_INPUT_CHUNK_TYPE_IMAGE) {
                if (mtmd_encode_chunk(mctx, chunk)) throw std::runtime_error("Vision encode failed.");
                float *embd = mtmd_get_output_embd(mctx);
                if (!embd) throw std::runtime_error("Vision encode returned no embeddings.");
                if (mtmd_helper_decode_image_chunk(mctx, ctx, chunk, embd, n_past, 0, 2048, &n_past, nullptr, nullptr))
                    throw std::runtime_error("Vision image prefill failed.");
            } else {
                throw std::runtime_error("Vision input contained an unsupported chunk.");
            }
            if (!cached && last_is_text && i + 2 == nch) {
                size_t bytes = llama_state_seq_get_size(ctx, 0);
                if (bytes > 0 && bytes <= kPrefixBytes) {
                    Prefix prefix;
                    prefix.data.resize(bytes);
                    prefix.n_past = n_past;
                    if (llama_state_seq_get_data(ctx, prefix.data.data(), bytes, 0) == bytes)
                        remember(key, std::move(prefix));
                }
            }
        }

        const llama_vocab *vocab = llama_model_get_vocab(model);
        std::string answer;
        int generated = 0;
        for (; generated < predict;) {
            llama_token token = llama_sampler_sample(sampler, ctx, -1);
            if (llama_vocab_is_eog(vocab, token)) break;
            std::string piece(64, '\0');
            int n = llama_token_to_piece(vocab, token, piece.data(), (int32_t)piece.size(), 0, false);
            if (n < 0) {
                piece.assign((size_t)(-n), '\0');
                n = llama_token_to_piece(vocab, token, piece.data(), (int32_t)piece.size(), 0, false);
            }
            if (n < 0) throw std::runtime_error("Vision could not decode a token.");
            piece.resize((size_t)n);
            answer += piece;
            if (on_token) {
                std::string terminated = piece;
                terminated.push_back('\0');
                on_token(terminated.c_str(), user);
            }
            ++generated;
            llama_batch batch = llama_batch_get_one(&token, 1);
            if (llama_decode(ctx, batch)) throw std::runtime_error("Vision decode failed.");
        }
        double elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
        nlohmann::json out = {
            {"ok", true},
            {"text", answer},
            {"tokens", generated},
            {"image_tokens", image_tokens},
            {"cached", cached},
            {"elapsed_ms", elapsed},
            {"detailed", detailed_query},
        };
        return out.dump();
    }
};

nlohmann::json parse_json(const char *text) {
    if (!text || !*text) return nlohmann::json::object();
    return nlohmann::json::parse(text);
}

std::filesystem::path weight_file(const nlohmann::json &config, const char *key, const std::filesystem::path &dir, const char *fallback) {
    if (config.contains(key) && config.at(key).is_string() && !config.at(key).get<std::string>().empty())
        return path_from_utf8(config.at(key).get<std::string>());
    return dir / fallback;
}

}  // namespace

extern "C" {

const char *smb_vision_runtime(void) {
    try {
        g_result = runtime_json();
        g_error.clear();
        return g_result.c_str();
    } catch (const std::exception &ex) {
        g_error = ex.what();
        g_result = std::string("{\"ok\":false,\"error\":") + nlohmann::json(g_error).dump() + "}";
        return g_result.c_str();
    }
}

const char *smb_vision_last_error(void) { return g_error.c_str(); }

void *smb_vision_create(const char *config_json) {
    try {
        ensure_backend();
        void *created = run_on_vision_stack([&]() -> void * {
        nlohmann::json config = parse_json(config_json);
        namespace fs = std::filesystem;
        fs::path dir = config.contains("model_dir") && config.at("model_dir").is_string() && !config.at("model_dir").get<std::string>().empty()
                           ? path_from_utf8(config.at("model_dir").get<std::string>())
                           : default_model_dir();
        fs::path llm = weight_file(config, "model_path", dir, kLlmName);
        fs::path mmproj = weight_file(config, "mmproj_path", dir, kMmprojName);
        fs::path llm_open = extended_path(llm);
        fs::path mmproj_open = extended_path(mmproj);
        if (!fs::is_regular_file(llm_open) || !fs::is_regular_file(mmproj_open)) {
            throw std::runtime_error(std::string(kMissingWeights) + " Expected " + display_path(llm) + " and " + display_path(mmproj) + ".");
        }
        std::string llm_utf8 = utf8_open_path(llm);
        std::string mmproj_utf8 = utf8_open_path(mmproj);
        int threads = config.value("n_threads", 0);
        if (threads <= 0) threads = physical_cores();
        if (threads > 256) threads = 256;
        int n_ctx = config.value("n_ctx", kDefaultCtx);
        if (n_ctx < 2048) n_ctx = 2048;
        if (n_ctx > 32768) n_ctx = 32768;
        int max_tokens = config.value("max_tokens", kDefaultMaxTokens);
        bool flash = config.value("flash_attn", true);
        bool detailed = config.value("detailed", false);
#ifdef SMB_VISION_HAS_METAL
        bool use_gpu = config.value("use_gpu", true);
#else
        bool use_gpu = config.value("use_gpu", false);
#endif
        bool warmup = config.value("warmup", true);

        auto engine = std::make_unique<Engine>();
        engine->threads = threads;
        engine->n_ctx = n_ctx;
        engine->max_tokens = max_tokens;
        engine->detailed = detailed;
        engine->model_hash = sha256_file(llm_utf8) + sha256_file(mmproj_utf8);

        llama_model_params model_params = llama_model_default_params();
        if (!use_gpu) model_params.n_gpu_layers = 0;
#if defined(_WIN32)
        // SIMD kernels read a few bytes past a tensor. Linux mmap zero-fills the
        // tail of the last page; Windows raises an access violation past EOF.
        model_params.load_mode = LLAMA_LOAD_MODE_NONE;
#endif
        engine->model = llama_model_load_from_file(llm_utf8.c_str(), model_params);
        if (!engine->model) throw std::runtime_error("Vision language model failed to load.");

        llama_context_params context_params = llama_context_default_params();
        context_params.n_ctx = static_cast<uint32_t>(n_ctx);
        context_params.n_batch = std::min<uint32_t>(2048, context_params.n_ctx);
        context_params.n_ubatch = std::min<uint32_t>(512, context_params.n_batch);
        context_params.n_threads = threads;
        context_params.n_threads_batch = threads;
        context_params.flash_attn_type = flash ? LLAMA_FLASH_ATTN_TYPE_ENABLED : LLAMA_FLASH_ATTN_TYPE_DISABLED;
        engine->ctx = llama_init_from_model(engine->model, context_params);
        if (!engine->ctx) throw std::runtime_error("Vision context failed to initialize.");

        mtmd_context_params mtmd_params = mtmd_context_params_default();
        mtmd_params.n_threads = threads;
        mtmd_params.use_gpu = use_gpu;
        mtmd_params.print_timings = false;
        mtmd_params.warmup = warmup;
        mtmd_params.flash_attn_type = context_params.flash_attn_type;
        engine->mctx = mtmd_init_from_file(mmproj_utf8.c_str(), engine->model, mtmd_params);
        if (!engine->mctx) throw std::runtime_error("Vision encoder failed to load.");
        engine->sampler = llama_sampler_init_greedy();
        if (!engine->sampler) throw std::runtime_error("Vision sampler failed to initialize.");
        return engine.release();
        });
        g_error.clear();
        return created;
    } catch (const std::exception &ex) {
        g_error = ex.what();
        return nullptr;
    }
}

const char *smb_vision_query_stream(void *handle, const char *image_path, const char *question, const char *options_json, smb_vision_token_fn on_token, void *user) {
    try {
        if (!handle) throw std::runtime_error("Vision engine is not loaded.");
        if (!image_path || !question) throw std::runtime_error("Vision image and question are required.");
        // A streaming callback may re-enter the host (Python holds the GIL on this
        // thread). Keep that call on the caller. Recognition passes a null callback
        // and, on Windows, runs on an 8 MiB worker.
        if (on_token) {
            nlohmann::json options = parse_json(options_json);
            g_result = static_cast<Engine *>(handle)->query(image_path, question, options, on_token, user);
        } else {
            g_result = run_on_vision_stack([&]() -> std::string {
                nlohmann::json options = parse_json(options_json);
                return static_cast<Engine *>(handle)->query(image_path, question, options, nullptr, nullptr);
            });
        }
        g_error.clear();
        return g_result.c_str();
    } catch (const std::exception &ex) {
        g_error = ex.what();
        g_result = nlohmann::json({{"ok", false}, {"error", g_error}}).dump();
        return g_result.c_str();
    }
}

const char *smb_vision_query(void *handle, const char *image_path, const char *question, const char *options_json) {
    return smb_vision_query_stream(handle, image_path, question, options_json, nullptr, nullptr);
}

void smb_vision_free(void *handle) { delete static_cast<Engine *>(handle); }

}  // extern "C"
