import os
import csv
import copy
import multiprocessing

import ujson
import subprocess

import numpy as np
import pandas as pd
from embeddings.embedding import Embedding
from gensim.models import FastText
from gensim.parsing import preprocess_string
from tqdm import tqdm

csv.field_size_limit(500 * 1024 * 1024)

path_data = os.environ['FNR_PATH_DATA'] if 'FNR_PATH_DATA' in os.environ else 'data/fake_news_corpus/'
news_cleaned_version = 'news_cleaned_2018_02_13'
path_news_cleaned = path_data + news_cleaned_version

path_news_csv = path_news_cleaned + '.csv'
path_fasttext = path_news_cleaned + '.fasttext.bin'
path_fasttext_db = path_news_cleaned + '.fasttext.db'
path_fasttext_jsonl = path_news_cleaned + '.fasttext.jsonl'
path_news_preprocessed = path_news_cleaned + '.preprocessed.jsonl'
path_news_shuffled = path_news_cleaned + '.preprocessed.shuffled.jsonl'

path_news_train = path_news_cleaned + '.preprocessed.shuffled.train.jsonl'
path_news_test = path_news_cleaned + '.preprocessed.shuffled.test.jsonl'
path_news_val = path_news_cleaned + '.preprocessed.shuffled.val.jsonl'

path_news_preprocessed_all = path_news_cleaned + '_all.preprocessed.jsonl'
path_news_shuffled_all = path_news_cleaned + '_all.preprocessed.shuffled.jsonl'
path_news_train_all = path_news_cleaned + '_all.preprocessed.shuffled.train.jsonl'
path_news_test_all = path_news_cleaned + '_all.preprocessed.shuffled.test.jsonl'
path_news_val_all = path_news_cleaned + '_all.preprocessed.shuffled.val.jsonl'

path_news_preprocessed_all_separate = path_news_cleaned + '_all_separate.preprocessed.jsonl'
path_news_shuffled_all_separate = path_news_cleaned + '_all_separate.preprocessed.shuffled.jsonl'
path_news_train_all_separate = path_news_cleaned + '_all_separate.preprocessed.shuffled.train.jsonl'
path_news_test_all_separate = path_news_cleaned + '_all_separate.preprocessed.shuffled.test.jsonl'
path_news_val_all_separate = path_news_cleaned + '_all_separate.preprocessed.shuffled.val.jsonl'

# path_news_train_embedded = path_news_cleaned + '.preprocessed.shuffled.embedded.train.jsonl'
# path_news_test_embedded = path_news_cleaned + '.preprocessed.shuffled.embedded.test.jsonl'
# path_news_val_embedded = path_news_cleaned + '.preprocessed.shuffled.embedded.val.jsonl'

news_labels = ['bias', 'clickbait', 'conspiracy', 'fake', 'hate', 'junksci', 'political', 'reliable', 'rumor',
               'satire', 'unreliable']


def load_fasttext():
    _fasttext = FastText.load_fasttext_format(path_fasttext)
    fasttext_dict = {}
    for word in tqdm(_fasttext.wv.vocab):
        fasttext_dict[word] = _fasttext[word]

    del _fasttext

    return fasttext_dict


def _news_generator_process_line(line, fasttext, max_words_content, separate=False, max_words_title=50):
    article = ujson.loads(line)

    embedding_content = np.zeros((max_words_content, 100))
    for i, word in enumerate(article['content'][:max_words_content]):
        if word in fasttext:
            embedding_content[i] = fasttext[word]

    if separate:
        embedding_title = np.zeros((max_words_title, 100))
        for i, word in enumerate(article['title'][:max_words_title]):
            if word in fasttext:
                embedding_title[i] = fasttext[word]

        return (embedding_title, embedding_content), article['label']

    return embedding_content, article['label']


def embedded_news_generator(path, batch, fasttext, max_words):
    while True:
        with open(path, 'r') as in_news:
            batch_i = 0
            batch_embedding = np.zeros((batch, max_words, 100))
            batch_label = np.zeros((batch, 1))
            for line in in_news:
                embedding, label = _news_generator_process_line(line, fasttext, max_words)

                if (batch_i + 1) == batch:
                    yield batch_embedding, batch_label
                    batch_embedding = np.zeros((batch, max_words, 100))
                    batch_label = np.zeros((batch, 1))
                    batch_i = 0
                else:
                    batch_embedding[batch_i] = embedding
                    batch_label[batch_i, 0] = label
                    batch_i += 1


def non_embedded_news_generator(path, batch, index_dict, max_words):
    while True:
        with open(path, 'r') as in_news:
            batch_i = 0
            batch_embedding = np.zeros((batch, max_words))
            batch_label = np.zeros((batch, 1))
            for line in in_news:
                article = ujson.loads(line)

                embedding_content = np.zeros((max_words))
                for i, word in enumerate(article['content'][:max_words]):
                    if word in index_dict:
                        embedding_content[i] = index_dict[word]

                if (batch_i + 1) == batch:
                    yield batch_embedding, batch_label
                    batch_embedding = np.zeros((batch, max_words))
                    batch_label = np.zeros((batch, 1))
                    batch_i = 0
                else:
                    batch_embedding[batch_i] = embedding_content
                    batch_label[batch_i, 0] = article['label']
                    batch_i += 1


def embedded_news_generator_separate(path, batch, fasttext, max_words_title, max_words_content):
    while True:
        with open(path, 'r') as in_news:
            batch_i = 0
            batch_embedding_title = np.zeros((batch, max_words_title, 100))
            batch_embedding_content = np.zeros((batch, max_words_content, 100))
            batch_label = np.zeros((batch, 1))
            for line in in_news:
                embedding, label = _news_generator_process_line(line, fasttext, max_words_content, True,
                                                                max_words_title)

                if label not in ('fake', 'conspiracy', 'unreliable', 'reliable'):
                    continue

                if (batch_i + 1) == batch:
                    yield [batch_embedding_title, batch_embedding_content], batch_label
                    batch_embedding_title = np.zeros((batch, max_words_title, 100))
                    batch_embedding_content = np.zeros((batch, max_words_content, 100))
                    batch_label = np.zeros((batch, 1))
                    batch_i = 0
                else:
                    batch_embedding_title[batch_i] = embedding[0]
                    batch_embedding_content[batch_i] = embedding[1]
                    batch_label[batch_i, 0] = 1 if label == 'reliable' else 0
                    batch_i += 1


def embedded_news_generator_all(path, batch, fasttext, max_words, labels=None):
    if labels is None:
        # removed unknown label
        labels = copy.deepcopy(news_labels)

    while True:
        with open(path, 'r') as in_news:
            batch_i = 0
            batch_embedding = np.zeros((batch, max_words, 100))
            batch_label = np.zeros((batch, len(labels)))
            for line in in_news:
                embedding, label = _news_generator_process_line(line, fasttext, max_words)

                if label not in labels:
                    continue

                if (batch_i + 1) == batch:
                    yield batch_embedding, batch_label
                    batch_embedding = np.zeros((batch, max_words, 100))
                    batch_label = np.zeros((batch, len(labels)))
                    batch_i = 0
                else:
                    batch_embedding[batch_i] = embedding
                    batch_label[batch_i, labels.index(label)] = 1
                    batch_i += 1


def _news_generator_db_process_line(line, max_words=300):
    e = Embedding()
    e.db = e.initialize_db(path_fasttext_db)

    article = ujson.loads(line)

    embedding = np.zeros((max_words, 100))
    for i, word in enumerate(article['content'][:max_words]):
        emb = e.lookup(word)
        if emb is not None:
            embedding[i] = emb

    return embedding, article['label']


def embedded_db_news_generator(path, batch, max_words):
    e = Embedding()
    e.db = e.initialize_db(path_fasttext_db)

    while True:
        with open(path, 'r') as in_news:
            batch_i = 0
            batch_label = np.zeros((batch, 1))
            batch_embedding = np.zeros((batch, max_words, 100))
            with multiprocessing.Pool(multiprocessing.cpu_count(), maxtasksperchild=1) as pool:
                for embedding, label in pool.imap(_news_generator_db_process_line, in_news, chunksize=10):
                    if (batch_i + 1) == batch:
                        yield batch_embedding, batch_label
                        batch_embedding = np.zeros((batch, max_words, 100))
                        batch_label = np.zeros((batch, 1))
                        batch_i = 0
                    else:
                        batch_embedding[batch_i] = embedding
                        batch_label[batch_i, 0] = label
                        batch_i += 1


# def hdf5_embedded_news_generator(path_embedded, batch):
#     while True:
#         with h5py.File(path_embedded, 'r') as in_embedded:
#             embeddings = in_embedded['embeddings']
#             labels = in_embedded['labels']
#
#             pointer = 0
#             while True:
#                 pointer_end = pointer + batch
#                 if embeddings.shape[0] <= pointer_end:
#                     # TODO: not perfect, misses few last articles :/
#                     break
#
#                 yield embeddings[pointer:pointer_end], labels[pointer:pointer_end]


def news_generator(binary=True, separate=False):
    with tqdm() as progress:
        for df_news_chunk in pd.read_csv(path_news_csv, encoding='utf-8', engine='python', chunksize=10 * 1000):
            if binary:
                news_filter = df_news_chunk.type.isin({'fake', 'conspiracy', 'unreliable', 'reliable'})
                df_news_chunk = df_news_chunk[news_filter]

            for row in df_news_chunk.itertuples():
                if binary:
                    label = 1 if row.type == 'reliable' else 0
                else:
                    label = row.type

                progress.update()
                if not isinstance(label, str):
                    continue

                try:
                    if separate:
                        yield int(row.id), (row.title, row.content), label
                    else:
                        yield int(row.id), '%s %s' % (row.title, row.content), label
                except Exception:
                    print(row)


def _preprocess_string(news):
    _id, con, label = news

    preprocessed_con = []
    if isinstance(con, tuple):
        for _con in con:
            preprocessed_con.append(preprocess_string(str(_con)))

        preprocessed_con = tuple(preprocessed_con)
    else:
        preprocessed_con = preprocess_string(con)

    return _id, preprocessed_con, label


def news_preprocessed_generator(binary=True, duplicates=True, separate=False):
    missing_words = {}

    counter = {'content_skipped': []}
    unique_hashes = {'content': set()}

    with multiprocessing.Pool(multiprocessing.cpu_count(), maxtasksperchild=1) as pool:
        for _id, con, label in pool.imap(_preprocess_string, news_generator(binary, separate), chunksize=1000):
            title = None
            if separate:
                title, con = con

            if not duplicates:
                if not isinstance(con, list):
                    continue

                content_hash = ''.join(con).__hash__()

                if content_hash in unique_hashes['content']:
                    counter['content_skipped'].append(_id)
                    continue

                unique_hashes['content'].add(content_hash)

            yield _id, ((title, con) if separate else con), label, missing_words

    print('Skiped', len(counter['content_skipped']))


def train_test_val_count(path):
    count_lines = 0
    with open(path, 'r') as in_news:
        for _ in tqdm(in_news):
            count_lines += 1

    train_size = int(count_lines * .8)
    test_size = int(count_lines * .1)
    val_size = count_lines - (train_size + test_size)

    return train_size, test_size, val_size, count_lines


def prepare_data():
    print('Preprocessing...')
    if not os.path.isfile(path_news_preprocessed):
        with open(path_news_preprocessed, 'w') as out_news_preprocessed:
            for _id, con, label, missing_words in news_preprocessed_generator():
                out_news_preprocessed.write(ujson.dumps({
                    'id': _id, 'content': con, 'label': int(label)
                }) + '\n')

    print('Shuffling...')
    if not os.path.isfile(path_news_shuffled):
        subprocess.call(['shuf', path_news_preprocessed, '>', path_news_shuffled])

    print('Counting...')
    train_size, test_size, val_size, count_lines = train_test_val_count(path_news_shuffled)

    print('Splitting into train, test, and val...')
    if not os.path.isfile(path_news_train) or not os.path.isfile(path_news_test) or not os.path.isfile(path_news_val):
        with open(path_news_shuffled, 'r') as in_news:
            with open(path_news_train, 'w') as out_train:
                with open(path_news_test, 'w') as out_test:
                    with open(path_news_val, 'w') as out_val:
                        for i, line in tqdm(enumerate(in_news)):
                            if i < train_size:
                                out_train.write(line)
                            elif i < (train_size + test_size):
                                out_test.write(line)
                            else:
                                out_val.write(line)

    # print('Loading fasttext...')
    # fasttext = FastText.load_fasttext_format(path_fasttext)
    #
    # print('Embedding...')
    # max_words = 300
    # chunk_size = 10 * 1000
    #
    # for path, path_embedded, size in [(path_news_train, path_news_train_embedded, train_size),
    #                                   (path_news_test, path_news_test_embedded, test_size),
    #                                   (path_news_val, path_news_val_embedded, val_size)]:
    #     with h5py.File(path_news_train_embedded, 'w') as out_embedded:
    #         dset_embedding = out_embedded.create_dataset('embeddings', (size, max_words, 100),
    #                                                      chunks=(chunk_size, max_words, 100), compression='gzip')
    #         dset_label = out_embedded.create_dataset('labels', (size, 1), chunks=(chunk_size, 1), compression='gzip')
    #
    #         pointer = 0
    #         for embedding, label in embedded_news_generator(path, chunk_size, fasttext, max_words):
    #             dset_embedding[pointer:(pointer + chunk_size), :, :] = embedding
    #             dset_label[pointer:(pointer + chunk_size), :] = label
    #             pointer += chunk_size


def prepare_all_data():
    print('Preprocessing...')
    if not os.path.isfile(path_news_preprocessed_all):
        with open(path_news_preprocessed_all, 'w') as out_news_preprocessed:
            for _id, con, label, missing_words in news_preprocessed_generator(binary=False, duplicates=False):
                out_news_preprocessed.write(ujson.dumps({
                    'id': _id, 'content': con, 'label': label
                }) + '\n')
    else:
        print('Data already prepared! 😊')

    print('Shuffling...')
    if not os.path.isfile(path_news_shuffled_all):
        subprocess.call(['shuf', path_news_preprocessed_all, '>', path_news_shuffled_all])
        # use shuffle instead: https://github.com/alexandres/lexvec/blob/master/shuffle.py

    print('Counting...')
    train_size, test_size, val_size, count_lines = train_test_val_count(path_news_shuffled_all)

    print('Splitting into train, test, and val...')
    if not os.path.isfile(path_news_train_all) or not os.path.isfile(path_news_test_all) or \
            not os.path.isfile(path_news_val_all):
        with open(path_news_shuffled_all, 'r') as in_news:
            with open(path_news_train_all, 'w') as out_train:
                with open(path_news_test_all, 'w') as out_test:
                    with open(path_news_val_all, 'w') as out_val:
                        for i, line in tqdm(enumerate(in_news)):
                            if i < train_size:
                                out_train.write(line)
                            elif i < (train_size + test_size):
                                out_test.write(line)
                            else:
                                out_val.write(line)


def prepare_all_separate_data():
    print('Preprocessing...')
    if not os.path.isfile(path_news_preprocessed_all_separate):
        with open(path_news_preprocessed_all_separate, 'w') as out_news_preprocessed:
            for _id, con, label, missing_words in news_preprocessed_generator(binary=False, duplicates=False,
                                                                              separate=True):
                out_news_preprocessed.write(ujson.dumps({
                    'id': _id, 'title': con[0], 'content': con[1], 'label': label
                }) + '\n')
    else:
        print('Data already prepared! 😊')

    print('Shuffling...')
    if not os.path.isfile(path_news_shuffled_all_separate):
        subprocess.call(['shuf', path_news_preprocessed_all_separate, '>', path_news_shuffled_all_separate])
        # use shuffle instead: https://github.com/alexandres/lexvec/blob/master/shuffle.py

    print('Counting...')
    train_size, test_size, val_size, count_lines = train_test_val_count(path_news_shuffled_all_separate)

    print('Splitting into train, test, and val...')
    if not os.path.isfile(path_news_train_all_separate) or not os.path.isfile(path_news_test_all_separate) or \
            not os.path.isfile(path_news_val_all_separate):
        with open(path_news_shuffled_all_separate, 'r') as in_news:
            with open(path_news_train_all_separate, 'w') as out_train:
                with open(path_news_test_all_separate, 'w') as out_test:
                    with open(path_news_val_all_separate, 'w') as out_val:
                        for i, line in tqdm(enumerate(in_news)):
                            if i < train_size:
                                out_train.write(line)
                            elif i < (train_size + test_size):
                                out_test.write(line)
                            else:
                                out_val.write(line)


if __name__ == '__main__':
    prepare_all_separate_data()
