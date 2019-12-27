import json
import os
import re
from os.path import dirname, exists, abspath, join

yelp_data_file = '/home/haotian/Downloads/yelp_dataset/review.json'
yelp_dataset = join(dirname(abspath(__file__)), 'yelp20k.txt')
yelp_dataset_test = join(dirname(abspath(__file__)),
                         'testdata', 'yelp20k_test.txt')

# if exists(yelp_dataset):
#     raise Exception(f'file: {yelp_dataset} already exists')

with open(yelp_data_file, 'r') as f:
    with open(yelp_dataset, 'w') as f_out:
        with open(yelp_dataset_test, 'w') as f_out_test:
            cnt = 0
            while cnt < 25000:
                # read file
                line = f.readline()
                if not line:
                    break
                print(cnt)
                json_content = json.loads(line)

                # parse review
                review = json_content['text']
                review = review.replace('\n', ' ').replace(
                    '\t', ' ').replace('\r', ' ').replace('  ', ' ').strip()

                # filter length
                # if len(review) < 150 or len(review) > 300:
                #     continue

                words_cnt = len(re.split(r"[],.!;:?\s]", review))
                if words_cnt < 70 or words_cnt > 100:
                    continue

                # write
                if cnt % 5 == 0:
                    f_out_test.write(review + '\n')
                else:
                    f_out.write(review + '\n')
                # print(review)
                cnt += 1
