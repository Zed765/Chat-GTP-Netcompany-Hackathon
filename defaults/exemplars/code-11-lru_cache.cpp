// A least-recently-used cache with a fixed capacity and hit statistics.

#include <cstddef>
#include <iostream>
#include <list>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

template <typename Key, typename Value>
class LruCache {
public:
    explicit LruCache(std::size_t capacity) : capacity_(capacity) {
        if (capacity == 0) {
            throw std::invalid_argument("capacity must be greater than zero");
        }
    }

    // Returns the value and marks the entry as most recently used.
    std::optional<Value> get(const Key& key) {
        auto found = index_.find(key);
        if (found == index_.end()) {
            ++misses_;
            return std::nullopt;
        }
        ++hits_;
        entries_.splice(entries_.begin(), entries_, found->second);
        return found->second->second;
    }

    // Inserts or replaces a value, evicting the least recently used entry when full.
    void put(const Key& key, Value value) {
        auto found = index_.find(key);
        if (found != index_.end()) {
            found->second->second = std::move(value);
            entries_.splice(entries_.begin(), entries_, found->second);
            return;
        }
        if (entries_.size() == capacity_) {
            index_.erase(entries_.back().first);
            entries_.pop_back();
            ++evictions_;
        }
        entries_.emplace_front(key, std::move(value));
        index_[key] = entries_.begin();
    }

    bool erase(const Key& key) {
        auto found = index_.find(key);
        if (found == index_.end()) {
            return false;
        }
        entries_.erase(found->second);
        index_.erase(found);
        return true;
    }

    void clear() {
        entries_.clear();
        index_.clear();
    }

    std::size_t size() const { return entries_.size(); }
    std::size_t capacity() const { return capacity_; }
    std::size_t evictions() const { return evictions_; }

    double hit_rate() const {
        const auto total = hits_ + misses_;
        return total == 0 ? 0.0 : static_cast<double>(hits_) / static_cast<double>(total);
    }

private:
    using Entry = std::pair<Key, Value>;

    std::size_t capacity_;
    std::list<Entry> entries_;
    std::unordered_map<Key, typename std::list<Entry>::iterator> index_;
    std::size_t hits_ = 0;
    std::size_t misses_ = 0;
    std::size_t evictions_ = 0;
};

int main() {
    LruCache<std::string, int> cache(2);
    cache.put("one", 1);
    cache.put("two", 2);
    cache.get("one");
    cache.put("three", 3);

    for (const std::string key : {"one", "two", "three"}) {
        const auto value = cache.get(key);
        std::cout << key << ": " << (value ? std::to_string(*value) : "evicted") << '\n';
    }
    std::cout << "hit rate " << cache.hit_rate() << ", evictions " << cache.evictions() << '\n';
    return 0;
}
